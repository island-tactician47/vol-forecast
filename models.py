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

from data_io import has_range

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


def _gjr_filter(params, r):
    mu, omega, alpha, gamma, beta = params
    p = alpha + 0.5 * gamma + beta
    s2 = np.empty(len(r) + 1)
    prev = omega / (1 - p) if p < 1 else float(np.var(r))  # 初期値は無条件分散
    s2[0] = prev
    for t, x in enumerate((r - mu).tolist()):
        a = alpha + gamma if x < 0 else alpha
        prev = omega + a * x * x + beta * prev
        s2[t + 1] = prev
    return s2


def _gjr_nll(params, r):
    mu, omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + gamma < 0 or alpha + 0.5 * gamma + beta >= 0.9999:
        return 1e10
    s2 = _gjr_filter(params, r)[:-1]
    if np.any(s2 <= 0):
        return 1e10
    e = r - mu
    return 0.5 * float(np.sum(np.log(s2) + e * e / s2))


class GJRGarch:
    """GJR-GARCH(1,1)（正規分布の擬似最尤）。下落時にボラが上がる非対称性を γ で表す。

    σ²_t = ω + (α + γ·1[e_{t-1}<0])·e²_{t-1} + β·σ²_{t-1}
    """
    name = "GJR-GARCH"

    def __init__(self):
        self.params = None

    def fit(self, df):
        r = df["ret"].to_numpy(float)
        v = float(np.var(r))
        x0 = [float(np.mean(r)), v * 0.05, 0.03, 0.08, 0.88]
        bounds = [(-1, 1), (1e-8, 10 * v), (0, 0.5), (-0.5, 0.5), (0, 0.9999)]
        cons = [
            {"type": "ineq", "fun": lambda x: 0.9999 - (x[2] + 0.5 * x[3] + x[4])},
            {"type": "ineq", "fun": lambda x: x[2] + x[3]},
        ]
        res = minimize(_gjr_nll, x0, args=(r,), method="SLSQP", bounds=bounds,
                       constraints=cons, options={"maxiter": 500})
        self.params = res.x if np.isfinite(res.fun) and res.fun < 1e9 else np.array(x0)
        return self

    @property
    def persistence(self):
        _, _, a, g, b = self.params
        return a + 0.5 * g + b

    def info(self):
        mu, omega, a, g, b = self.params
        p = self.persistence
        return {
            "mu": mu, "omega": omega, "alpha": a, "gamma": g, "beta": b,
            "persistence": p,
            "half_life_days": np.log(0.5) / np.log(p) if 0 < p < 1 else None,
            "long_run_vol_ann": np.sqrt(omega / (1 - p) * TRADING_DAYS) if p < 1 else None,
        }

    def one_step(self, df):
        return pd.Series(_gjr_filter(self.params, df["ret"].to_numpy(float))[:-1], index=df.index)

    def mean(self):
        return float(self.params[0])

    def forecast(self, df, h):
        omega, p = self.params[1], self.persistence
        v = [_gjr_filter(self.params, df["ret"].to_numpy(float))[-1]]
        for _ in range(h - 1):
            v.append(omega + p * v[-1])  # E[σ²_{t+k}] の漸化式
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
    def _features(rv):
        X = pd.DataFrame({
            "d": np.log(rv),
            "w": np.log(rv.rolling(5).mean()),
            "m": np.log(rv.rolling(22).mean()),
        })
        X.insert(0, "const", 1.0)
        return X

    def fit(self, df):
        rv = df["rv"]
        self.scale = float((df["ret"] ** 2).mean() / rv.mean())
        X = self._features(rv)
        y = np.log(rv)
        self.coefs = {}
        for k in range(1, self.horizon + 1):
            d = pd.concat([X, y.shift(-k).rename("y")], axis=1).dropna()
            b, *_ = np.linalg.lstsq(d[X.columns].to_numpy(), d["y"].to_numpy(), rcond=None)
            resid = d["y"].to_numpy() - d[X.columns].to_numpy() @ b
            self.coefs[k] = (b, float(np.var(resid)))
        return self

    def _predict(self, X, k):
        b, s2 = self.coefs[k]
        return self.scale * np.exp(X.to_numpy() @ b + 0.5 * s2)  # 対数正規のバイアス補正

    def one_step(self, df):
        X = self._features(df["rv"])
        return pd.Series(self._predict(X, 1), index=df.index).shift(1)

    def forecast(self, df, h):
        X = self._features(df["rv"]).iloc[[-1]]
        return np.array([float(self._predict(X, k)[0]) for k in range(1, h + 1)])


def build_models(df, horizon):
    models = [GJRGarch(), EWMA(), HistVol()]
    if has_range(df):
        models.append(HAR(horizon))
    return models
