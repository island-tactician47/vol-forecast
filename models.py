"""ボラティリティ予測モデル。

共通インターフェース（リターンは % 単位の日次対数リターン df["ret"]）:
  fit(df)          : パラメータ推定
  one_step(df)     : 各日 t の分散予測（t-1 までの情報で作ったもの）を df と同じ index で返す
  forecast(df, h)  : df の最終日の翌営業日から h 日分の分散予測（%^2）を返す
  multi_step(df, h): 各行 t について「t までの情報で作った t+1..t+h 日先の分散予測」を表（列 1..h）で返す
                     （検証で k 日先の精度を測るため。1列目を1行ずらしたものが one_step と一致する）
新しいモデルを足すときは同じ3メソッドを持つクラスを作り、build_models() に加える。
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

from config import EXOG_MODELS, EXTRA_MODELS, SCALE_WINDOW
from data_io import has_exog, has_iv, has_range

TRADING_DAYS = 252


class HistVol:
    """過去20日の二乗リターン平均（素朴な基準）。"""
    name = "HIST20"

    def __init__(self, window=20):
        self.window = window

    def fit(self, df):
        return self

    def one_step(self, df):
        return (df["ret"] ** 2).rolling(self.window).mean().shift(1)

    def forecast(self, df, h):
        return np.full(h, float((df["ret"].iloc[-self.window:] ** 2).mean()))

    def multi_step(self, df, h):
        v = (df["ret"] ** 2).rolling(self.window).mean()
        return pd.DataFrame({k: v for k in range(1, h + 1)})


def _ewma(r, lam):
    s2 = np.empty(len(r) + 1)
    prev = float(np.mean(r[:20] ** 2))
    s2[0] = prev
    for t, x in enumerate(r.tolist()):
        prev = lam * prev + (1 - lam) * x * x
        s2[t + 1] = prev
    return s2


class EWMA:
    """RiskMetrics型の指数加重（λ=0.94）。実務の定番ベンチマーク。"""
    name = "EWMA"

    def __init__(self, lam=0.94):
        self.lam = lam

    def fit(self, df):
        return self

    def one_step(self, df):
        return pd.Series(_ewma(df["ret"].to_numpy(float), self.lam)[:-1], index=df.index)

    def forecast(self, df, h):
        return np.full(h, _ewma(df["ret"].to_numpy(float), self.lam)[-1])

    def multi_step(self, df, h):
        v = pd.Series(_ewma(df["ret"].to_numpy(float), self.lam)[1:], index=df.index)
        return pd.DataFrame({k: v for k in range(1, h + 1)})


def _gjr_filter(params, r, x=None, xn=None):
    """σ²_t = ω + (α + γ·1[e<0])·e²_{t-1} + β·σ²_{t-1} + δ·x_t + δn·xn_t

    x, xn は長さ len(r)+1（最後は翌日分）。None なら外部変数なし。
    戻り値 s2 は長さ len(r)+1 で、s2[t] が日 t の分散、s2[-1] が翌日の予測。
    """
    mu, omega, alpha, gamma, beta = params[:5]
    d, dn = (params[5], params[6]) if x is not None else (0.0, 0.0)
    p = alpha + 0.5 * gamma + beta
    ex = d * x + dn * xn if x is not None else np.zeros(len(r) + 1)
    s2 = np.empty(len(r) + 1)
    base = omega + float(np.mean(ex))
    prev = base / (1 - p) if p < 1 else float(np.var(r))  # 初期値は無条件分散
    s2[0] = prev
    exl = ex.tolist()
    for t, e in enumerate((r - mu).tolist()):
        a = alpha + gamma if e < 0 else alpha
        prev = omega + a * e * e + beta * prev + exl[t + 1]
        s2[t + 1] = prev
    return s2


def _gjr_nll(params, r, x=None, xn=None):
    mu, omega, alpha, gamma, beta = params[:5]
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + gamma < 0 or alpha + 0.5 * gamma + beta >= 0.9999:
        return 1e10
    if x is not None and (params[5] < 0 or params[5] + params[6] < 0):
        return 1e10
    s2 = _gjr_filter(params, r, x, xn)[:-1]
    if np.any(s2 <= 0):
        return 1e10
    e = r - mu
    return 0.5 * float(np.sum(np.log(s2) + e * e / s2))


def _exog_arrays(df):
    """GJR用：日 0..n-1 の x と、最後に翌日分 x_next を足した長さ n+1 の配列。"""
    if not has_exog(df):
        return None, None
    x = np.append(df["x"].to_numpy(float), df["x_next"].iloc[-1])
    xn = np.append(df["xn"].to_numpy(float), df["xn_next"].iloc[-1])
    return x, xn


class GJRGarch:
    """GJR-GARCH(1,1)（正規分布の擬似最尤）。下落時にボラが上がる非対称性を γ で表す。

    σ²_t = ω + (α + γ·1[e_{t-1}<0])·e²_{t-1} + β·σ²_{t-1}  ( + δ·x_t + δn·xn_t )
    外部変数（data_io.add_exog）がある銘柄では、先行市場の前夜の変動 x と、その下落分 xn を加える。
    """
    name = "GJR-GARCH"

    def __init__(self):
        self.params = None
        self.exog = False

    def fit(self, df):
        r = df["ret"].to_numpy(float)
        x, xn = _exog_arrays(df) if self.name in EXOG_MODELS else (None, None)
        self.exog = x is not None
        v = float(np.var(r))
        x0 = [float(np.mean(r)), v * 0.05, 0.03, 0.08, 0.88]
        bounds = [(-1, 1), (1e-8, 10 * v), (0, 0.5), (-0.5, 0.5), (0, 0.9999)]
        cons = [
            {"type": "ineq", "fun": lambda p: 0.9999 - (p[2] + 0.5 * p[3] + p[4])},
            {"type": "ineq", "fun": lambda p: p[2] + p[3]},
        ]
        if self.exog:
            x0 = [x0[0], v * 0.02, 0.02, 0.05, 0.85, 0.05, 0.05]
            bounds += [(0, 2), (-2, 2)]
            cons.append({"type": "ineq", "fun": lambda p: p[5] + p[6]})
        res = minimize(_gjr_nll, x0, args=(r, x, xn), method="SLSQP", bounds=bounds,
                       constraints=cons, options={"maxiter": 500})
        self.params = res.x if np.isfinite(res.fun) and res.fun < 1e9 else np.array(x0)
        self._x_mean = (self.params[5] * float(np.mean(x)) + self.params[6] * float(np.mean(xn))) if self.exog else 0.0
        return self

    @property
    def persistence(self):
        _, _, a, g, b = self.params[:5]
        return a + 0.5 * g + b

    def info(self):
        mu, omega, a, g, b = self.params[:5]
        p = self.persistence
        out = {
            "mu": mu, "omega": omega, "alpha": a, "gamma": g, "beta": b,
            "persistence": p,
            "half_life_days": np.log(0.5) / np.log(p) if 0 < p < 1 else None,
            "long_run_vol_ann": np.sqrt((omega + self._x_mean) / (1 - p) * TRADING_DAYS) if p < 1 else None,
        }
        if self.exog:
            out.update({"delta": self.params[5], "delta_neg": self.params[6]})
        return out

    def _filter(self, df):
        x, xn = _exog_arrays(df) if self.exog else (None, None)
        return _gjr_filter(self.params, df["ret"].to_numpy(float), x, xn)

    def one_step(self, df):
        return pd.Series(self._filter(df)[:-1], index=df.index)

    def mean(self):
        return float(self.params[0])

    def forecast(self, df, h):
        omega, p = self.params[1], self.persistence
        if self.exog:  # 2日目以降の先行市場の変動は未知なので、直近22日の水準で代用
            recent = df.iloc[-22:]
            ex_k = self.params[5] * float(recent["x"].mean()) + self.params[6] * float(recent["xn"].mean())
        else:
            ex_k = 0.0
        v = [self._filter(df)[-1]]
        for _ in range(h - 1):
            v.append(omega + ex_k + p * v[-1])  # E[σ²_{t+k}] の漸化式
        return np.array(v)

    def multi_step(self, df, h):
        omega, p = self.params[1], self.persistence
        if self.exog:
            ex_k = (self.params[5] * df["x"].rolling(22, min_periods=1).mean()
                    + self.params[6] * df["xn"].rolling(22, min_periods=1).mean()).to_numpy()
        else:
            ex_k = 0.0
        v = self._filter(df)[1:]
        cols = {1: v}
        for k in range(2, h + 1):
            v = omega + ex_k + p * v
            cols[k] = v
        return pd.DataFrame(cols, index=df.index)


class HAR:
    """HAR-RV（Corsi 2009）。日・週・月の実現ボラで将来の実現ボラを回帰する。

    日足しかないので実現分散はParkinson推定量（高値・安値）で代用し、
    夜間の窓を含む終値ベースの水準に合うよう scale で補正する。
    scale は直近 SCALE_WINDOW 日の（終値ベースの分散 / Parkinson）で毎日測り直す（固定値だと水準がずれる銘柄があるため）。
    log をとって回帰し、予測ごとに k 日先を直接推定する（direct方式）。
    use_iv=True なら、インプライド・ボラティリティ（VIXなど）の水準も説明変数に加える（HAR-RV+IV）。
    """
    base_name = "HAR-RV"

    def __init__(self, horizon=5, use_iv=False, scale_window=SCALE_WINDOW):
        self.horizon = horizon
        self.use_iv = use_iv
        self.scale_window = scale_window
        self.name = "HAR-RV+IV" if use_iv else "HAR-RV"

    def _features(self, df):
        rv = df["rv"]
        X = pd.DataFrame({
            "d": np.log(rv),
            "w": np.log(rv.rolling(5).mean()),
            "m": np.log(rv.rolling(22).mean()),
        })
        if has_exog(df) and self.base_name in EXOG_MODELS:  # 翌日の寄り付き前に分かる先行市場の変動（HAR-X）
            X["x"] = np.log(df["x_next"] + 0.01)
            X["xn"] = np.log(df["xn_next"] + 0.01)
        if self.use_iv:
            X["iv"] = df["iv"]
        X.insert(0, "const", 1.0)
        return X

    def _scale_series(self, df):
        """各行 t の scale（t までのデータだけで計算）。窓が足りない間は fit 時の全期間の値。"""
        if not self.scale_window:
            return np.full(len(df), self.scale)
        w = self.scale_window
        a = (df["ret"] ** 2).rolling(w, min_periods=w // 2).mean()
        b = df["rv"].rolling(w, min_periods=w // 2).mean()
        return (a / b).fillna(self.scale).to_numpy()

    def fit(self, df):
        rv = df["rv"]
        self.scale = float((df["ret"] ** 2).mean() / rv.mean())
        X = self._features(df)
        y = np.log(rv)
        self.coefs = {}
        for k in range(1, self.horizon + 1):
            d = pd.concat([X, y.shift(-k).rename("y")], axis=1).dropna()
            b, *_ = np.linalg.lstsq(d[X.columns].to_numpy(), d["y"].to_numpy(), rcond=None)
            resid = d["y"].to_numpy() - d[X.columns].to_numpy() @ b
            self.coefs[k] = (b, float(np.var(resid)))
        self.scale_now = float(self._scale_series(df)[-1])
        self._cols = list(X.columns)
        return self

    def info(self):
        b, _ = self.coefs[1]
        names = {"const": "const", "d": "beta_d", "w": "beta_w", "m": "beta_m",
                 "x": "beta_x", "xn": "beta_xn", "iv": "beta_iv"}
        out = {names[c]: v for c, v in zip(self._cols, b)}
        out["scale"] = self.scale_now
        return out

    def _predict(self, X, k, sc):
        b, s2 = self.coefs[k]
        return sc * np.exp(X.to_numpy() @ b + 0.5 * s2)  # 対数正規のバイアス補正

    def one_step(self, df):
        X = self._features(df)
        return pd.Series(self._predict(X, 1, self._scale_series(df)), index=df.index).shift(1)

    def multi_step(self, df, h):
        X, sc = self._features(df), self._scale_series(df)
        return pd.DataFrame({k: self._predict(X, k, sc) for k in range(1, h + 1)}, index=df.index)

    def forecast(self, df, h):
        X, sc = self._features(df).iloc[[-1]], self._scale_series(df)[-1:]
        return np.array([float(self._predict(X, k, sc)[0]) for k in range(1, h + 1)])


def _gjr_t_nll(params, r):
    mu, omega, alpha, gamma, beta, nu = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + gamma < 0 or alpha + 0.5 * gamma + beta >= 0.9999 or nu <= 2.05:
        return 1e10
    s2 = _gjr_filter(params[:5], r)[:-1]
    if np.any(s2 <= 0):
        return 1e10
    e2 = (r - mu) ** 2 / s2
    n = len(r)
    const = n * (gammaln((nu + 1) / 2) - gammaln(nu / 2) - 0.5 * np.log(np.pi * (nu - 2)))
    return -const + 0.5 * float(np.sum(np.log(s2))) + 0.5 * (nu + 1) * float(np.sum(np.log1p(e2 / (nu - 2))))


class GJRGarchT(GJRGarch):
    """GJR-GARCH(1,1) の誤差をスチューデントt分布にしたもの（裾の厚さをパラメータ ν で表す）。"""
    name = "GJR-t"

    def fit(self, df):
        r = df["ret"].to_numpy(float)
        self.exog = False
        v = float(np.var(r))
        x0 = [float(np.mean(r)), v * 0.05, 0.03, 0.08, 0.88, 8.0]
        bounds = [(-1, 1), (1e-8, 10 * v), (0, 0.5), (-0.5, 0.5), (0, 0.9999), (2.1, 60)]
        cons = [{"type": "ineq", "fun": lambda p: 0.9999 - (p[2] + 0.5 * p[3] + p[4])},
                {"type": "ineq", "fun": lambda p: p[2] + p[3]}]
        res = minimize(_gjr_t_nll, x0, args=(r,), method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 500})
        ok = np.isfinite(res.fun) and res.fun < 1e9
        if not ok:
            print(f"  {self.name}: 推定が収束しませんでした（初期値を使用）")
        self.params = res.x if ok else np.array(x0)
        self._x_mean = 0.0
        self.nu = float(self.params[5])
        return self

    def info(self):
        out = super().info()
        out["nu"] = self.nu
        return out


def _egarch_filter(params, r):
    """log σ²_t = ω + β·log σ²_{t-1} + α(|z|−√(2/π)) + γ·z。戻り値は長さ len(r)+1 の log σ²（最後は翌日分）。"""
    mu, omega, alpha, gamma, beta = params
    c = np.sqrt(2 / np.pi)
    l = np.empty(len(r) + 1)
    prev = float(np.log(np.mean(r[:20] ** 2) + 1e-8))   # 初期値は最初の20日から（全期間を使うと将来の情報が混ざるため）
    l[0] = prev
    for t, e in enumerate((r - mu).tolist()):
        z = e / np.exp(0.5 * prev)
        prev = omega + beta * prev + alpha * (abs(z) - c) + gamma * z
        prev = min(max(prev, -25.0), 25.0)
        l[t + 1] = prev
    return l


def _egarch_nll(params, r):
    if abs(params[4]) >= 0.9999:
        return 1e10
    l = _egarch_filter(params, r)[:-1]
    e = r - params[0]
    return 0.5 * float(np.sum(l + e * e / np.exp(l)))


class EGARCH:
    """EGARCH(1,1)（正規分布の擬似最尤）。分散ではなく対数分散をモデル化するので、符号の制約が不要。γ<0 なら下落でボラが上がる。"""
    name = "EGARCH"
    SIMS = 300

    def fit(self, df):
        r = df["ret"].to_numpy(float)
        x0 = [float(np.mean(r)), 0.01, 0.10, -0.05, 0.97]
        bounds = [(-1, 1), (-1, 1), (0, 1), (-1, 1), (0, 0.9999)]
        res = minimize(_egarch_nll, x0, args=(r,), method="SLSQP", bounds=bounds, options={"maxiter": 400})
        ok = np.isfinite(res.fun) and res.fun < 1e9
        if not ok:
            print(f"  {self.name}: 推定が収束しませんでした（初期値を使用）")
        self.params = res.x if ok else np.array(x0)
        return self

    def mean(self):
        return float(self.params[0])

    def info(self):
        mu, omega, a, g, b = self.params
        return {"mu": mu, "omega": omega, "alpha": a, "gamma": g, "beta": b, "persistence": b}

    def one_step(self, df):
        return pd.Series(np.exp(_egarch_filter(self.params, df["ret"].to_numpy(float))[:-1]), index=df.index)

    def multi_step(self, df, h):
        """2日目以降は、標準化残差を正規乱数で何通りか流して E[σ²] を求める（乱数は固定で、全行で同じ列を使う）。"""
        _, omega, alpha, gamma, beta = self.params
        c = np.sqrt(2 / np.pi)
        l = _egarch_filter(self.params, df["ret"].to_numpy(float))[1:]   # 行 t に対する翌日の log σ²
        cols = {1: np.exp(l)}
        rng = np.random.default_rng(12345)
        ls = np.repeat(l[:, None], self.SIMS, axis=1)
        for k in range(2, h + 1):
            z = rng.standard_normal(self.SIMS)[None, :]   # 全行で同じ乱数列（データの長さに依存しない）
            ls = np.clip(omega + beta * ls + alpha * (np.abs(z) - c) + gamma * z, -25.0, 25.0)
            cols[k] = np.exp(ls).mean(axis=1)
        return pd.DataFrame(cols, index=df.index)

    def forecast(self, df, h):
        return self.multi_step(df, h).iloc[-1].to_numpy(float)


def build_models(df, horizon):
    models = [GJRGarch(), EWMA(), HistVol()]
    if EXTRA_MODELS:  # 比較用（主モデルは config.MAIN_MODEL のまま）
        models += [GJRGarchT(), EGARCH()]
    if has_range(df):
        models.append(HAR(horizon))
        if EXTRA_MODELS and has_iv(df):
            models.append(HAR(horizon, use_iv=True))
    return models
