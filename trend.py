"""方向の見立て：k営業日後の終値が、今日の終値より上になる確率を出す（k=1..HORIZON）。

当たりにくい予想であることは承知の上で出す。そのため、過去の当たり具合（拡大窓の検証）も必ず一緒に出す。

- 特徴量：直近の値動きのパターン（過去5・20・60・120・250日の騰落率を普段の変動で割ったもの、200日移動平均からの乖離、
  直近20日と250日の変動の比）。どれもその日までのデータだけで計算する
- モデル：L2正則化つきロジスティック回帰（TREND_RIDGE。強く縮めてあるので、確率は「平年の上昇率」に近いところに寄る）
- 検証：直近 TEST_YEARS 年を、REFIT_DAYS ごとに過去データだけで推定し直して、1日先・5日先を採点する。
  比べる相手は「平年の上昇率（学習期間の上昇率）で多い方を毎回答える」予想（的中率）と、平年の上昇率だけの確率（対数損失）
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import HORIZON, REFIT_DAYS, TEST_YEARS, TREND_BAND, TREND_RIDGE
from models import TRADING_DAYS

WINDOWS = (5, 20, 60, 120, 250)


def features(df):
    """各行 t（t日の引け後）の特徴量。t までのデータだけを使う。"""
    ret = df["ret"]
    sd = ret.rolling(750, min_periods=250).std()
    X = pd.DataFrame(index=df.index)
    for w in WINDOWS:
        X[f"r{w}"] = ret.rolling(w).sum() / (sd * np.sqrt(w))
    X["ma200"] = np.log(df["close"] / df["close"].rolling(200).mean()) / (sd * np.sqrt(200) / 100)
    X["vr"] = np.log(np.sqrt((ret ** 2).rolling(20).mean()) / np.sqrt((ret ** 2).rolling(250).mean()))
    return X.replace([np.inf, -np.inf], np.nan)


def future_up(df, k):
    """k営業日後までの累積リターンが正なら1、負なら0（未来が無い行は NaN）。"""
    cum = df["ret"].rolling(k).sum().shift(-k)
    return (cum > 0).astype(float).where(cum.notna())


def _fit(X, y, lam):
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = ((X - mu) / sd).to_numpy()
    yy = y.to_numpy()

    def f(p):
        z = Z @ p[:-1] + p[-1]
        loss = np.sum(np.logaddexp(0, z) - yy * z) + 0.5 * lam * p[:-1] @ p[:-1]
        g = 1 / (1 + np.exp(-z)) - yy
        return loss, np.append(Z.T @ g + lam * p[:-1], g.sum())

    p0 = np.zeros(Z.shape[1] + 1)
    p0[-1] = np.log(yy.mean() / (1 - yy.mean()))
    res = minimize(f, p0, jac=True, method="L-BFGS-B")
    return {"mu": mu, "sd": sd, "p": res.x, "base": float(yy.mean())}


def _predict(m, X):
    Z = ((X - m["mu"]) / m["sd"]).to_numpy()
    return 1 / (1 + np.exp(-(Z @ m["p"][:-1] + m["p"][-1])))


def _loss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _logloss(p, y):
    return float(np.mean(_loss(p, y)))


def _tstat(d, lag):
    """損失差 d の平均が0かの t 統計量（Newey-West。k日先の目標は重なるので、その分を補正）。負なら比べた方（モデル）が良い。"""
    u = d - d.mean()
    var = u @ u / len(d)
    for j in range(1, lag + 1):
        var += 2 * (1 - j / (lag + 1)) * (u[j:] @ u[:-j]) / len(d)
    return float(d.mean() / np.sqrt(var / len(d))) if var > 0 else 0.0


def forecast_trend(df):
    """今日の引け後の、k営業日後までに上がる確率（k=1..HORIZON）と、平年の上昇率。"""
    X = features(df)
    out = []
    for k in range(1, HORIZON + 1):
        y = future_up(df, k)
        ok = X.notna().all(axis=1) & y.notna()
        m = _fit(X[ok], y[ok], TREND_RIDGE)
        p = float(_predict(m, X.iloc[[-1]])[0]) if X.iloc[-1].notna().all() else m["base"]
        out.append({"k": k, "p_up": p, "base": m["base"]})
    return out


def label_of(p, base):
    """平年の上昇率からのずれで、上向き気味／下向き気味／方向感なし。"""
    d = p - base
    if d >= TREND_BAND:
        return {"label": "上向き気味", "arrow": "↗", "cls": "up"}
    if d <= -TREND_BAND:
        return {"label": "下向き気味", "arrow": "↘", "cls": "down"}
    return {"label": "方向感なし", "arrow": "→", "cls": "flat"}


def evaluate(df, ks=(1, HORIZON)):
    """直近 TEST_YEARS 年の拡大窓の検証。k日先ごとに、的中率・平年との比較・対数損失を返す。"""
    n = len(df)
    start = n - TEST_YEARS * TRADING_DAYS
    X = features(df)
    res = {}
    for k in ks:
        y = future_up(df, k)
        P, B, Y, L = [], [], [], []
        for b in range(start, n, REFIT_DAYS):
            e = min(b + REFIT_DAYS, n)
            tr = X.iloc[:b - k]                      # 目標が b-1 までに確定している行だけで学習
            ok = tr.notna().all(axis=1) & y.iloc[:b - k].notna()
            m = _fit(tr[ok], y.iloc[:b - k][ok], TREND_RIDGE)
            te = X.iloc[b:e]
            tok = te.notna().all(axis=1) & y.iloc[b:e].notna()
            if tok.sum() == 0:
                continue
            P.append(_predict(m, te[tok]))
            B.append(np.full(int(tok.sum()), m["base"]))
            Y.append(y.iloc[b:e][tok].to_numpy())
        if not P:
            continue
        P, B, Y = np.concatenate(P), np.concatenate(B), np.concatenate(Y)
        pred_up = P >= 0.5
        base_up = B >= 0.5
        acc, acc_base = float(np.mean(pred_up == (Y == 1))), float(np.mean(base_up == (Y == 1)))
        ll, ll_base = _logloss(P, Y), _logloss(B, Y)
        conf = np.abs(P - B) >= TREND_BAND            # 「上向き気味／下向き気味」と言った日だけ
        res[k] = {
            "n": int(len(Y)), "acc": acc * 100, "acc_base": acc_base * 100, "up_rate": float(Y.mean() * 100),
            "logloss": ll, "logloss_base": ll_base, "skill": 1 - ll / ll_base,   # >0 なら平年の上昇率だけより良い
            "t": _tstat(_loss(P, Y) - _loss(B, Y), max(5, k)),                  # -2 以下なら、有意に良い
            "n_conf": int(conf.sum()),
            "acc_conf": float(np.mean(pred_up[conf] == (Y[conf] == 1)) * 100) if conf.sum() >= 20 else None,
        }
    return res


def grade_of(ev):
    """△＝ほぼ当たらない（平年の上昇率だけの予想と区別できない）／○＝1日先と5日先の両方で、平年の上昇率だけの予想より
    対数損失が有意に良い（t ≤ -2）。ノイズで○にならないよう、有意性で決める。"""
    if ev and all(e["t"] <= -2.0 for e in ev.values()):
        return "○"
    return "△"
