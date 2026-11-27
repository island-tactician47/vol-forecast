"""ボラティリティ予測モデル。

共通インターフェース（リターンは % 単位の日次対数リターン df["ret"]）:
  fit(df)          : パラメータ推定
  one_step(df)     : 各日 t の分散予測（t-1 までの情報で作ったもの）を df と同じ index で返す
  forecast(df, h)  : df の最終日の翌営業日から h 日分の分散予測（%^2）を返す
新しいモデルを足すときは同じ3メソッドを持つクラスを作り、build_models() に加える。
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import EXOG_MODELS
from data_io import has_exog, has_range

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


class HAR:
    """HAR-RV（Corsi 2009）。日・週・月の実現ボラで将来の実現ボラを回帰する。

    日足しかないので実現分散はParkinson推定量（高値・安値）で代用し、
    夜間の窓を含む終値ベースの水準に合うよう scale で補正する。
    log をとって回帰し、予測ごとに k 日先を直接推定する（direct方式）。
    """
    name = "HAR-RV"

    def __init__(self, horizon=5):
        self.horizon = horizon

    @staticmethod
    def _features(df):
        rv = df["rv"]
        X = pd.DataFrame({
            "d": np.log(rv),
            "w": np.log(rv.rolling(5).mean()),
            "m": np.log(rv.rolling(22).mean()),
        })
        if has_exog(df) and HAR.name in EXOG_MODELS:  # 翌日の寄り付き前に分かる先行市場の変動（HAR-X）
            X["x"] = np.log(df["x_next"] + 0.01)
            X["xn"] = np.log(df["xn_next"] + 0.01)
        X.insert(0, "const", 1.0)
        return X

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
        return self

    def info(self):
        b, _ = self.coefs[1]
        names = ["const", "beta_d", "beta_w", "beta_m", "beta_x", "beta_xn"]
        out = dict(zip(names, b))
        out["scale"] = self.scale
        return out

    def _predict(self, X, k):
        b, s2 = self.coefs[k]
        return self.scale * np.exp(X.to_numpy() @ b + 0.5 * s2)  # 対数正規のバイアス補正

    def one_step(self, df):
        X = self._features(df)
        return pd.Series(self._predict(X, 1), index=df.index).shift(1)

    def forecast(self, df, h):
        X = self._features(df).iloc[[-1]]
        return np.array([float(self._predict(X, k)[0]) for k in range(1, h + 1)])


def build_models(df, horizon):
    models = [GJRGarch(), EWMA(), HistVol()]
    if has_range(df):
        models.append(HAR(horizon))
    return models
