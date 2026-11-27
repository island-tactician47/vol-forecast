"""価格CSVの読み込みとリターン計算（各スクリプト共通）。"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

from config import DATA_DIR, TICKERS, WEB_DATA_DIR


def display_name(key):
    return TICKERS[key][0] if key in TICKERS else key


def list_datasets():
    """data/ にあるCSVのキー（拡張子なしファイル名）一覧。"""
    DATA_DIR.mkdir(exist_ok=True)
    return sorted(p.stem for p in DATA_DIR.glob("*.csv"))


def _find(columns, candidates):
    low = {str(c).lower().strip(): c for c in columns}
    for k in candidates:
        if k in low:
            return low[k]
    return None


def load_prices(key):
    """CSVを読み、index=日付、列 close（必須）/ open / high / low（任意）の表を返す。

    想定する形式:
      - data_fetch.py が書く形式（Date, Open, High, Low, Close）
      - FREDの形式（observation_date / DATE, 値の列。欠損は "."）
      - その他、1列目が日付で Close / 終値 などの列があるもの
    """
    raw = pd.read_csv(DATA_DIR / f"{key}.csv")
    date_col = _find(raw.columns, ["date", "datetime", "observation_date", "日付"]) or raw.columns[0]
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    raw = raw.dropna(subset=[date_col]).set_index(date_col).sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]

    close_col = _find(raw.columns, ["close", "adj close", "終値"])
    if close_col is None:  # FREDなど：数値として読める値が一番多い列
        num = raw.apply(pd.to_numeric, errors="coerce")
        close_col = num.notna().sum().idxmax()

    out = pd.DataFrame(index=raw.index)
    out["close"] = pd.to_numeric(raw[close_col], errors="coerce")
    for name, cands in [("open", ["open", "始値"]), ("high", ["high", "高値"]), ("low", ["low", "安値"])]:
        c = _find(raw.columns, cands)
        if c is not None:
            out[name] = pd.to_numeric(raw[c], errors="coerce")
    out = out.dropna(subset=["close"])
    return out[out["close"] > 0]


def make_returns(px):
    """日次対数リターン（%）と、高値・安値があればParkinsonの日次分散（%^2）。"""
    df = pd.DataFrame(index=px.index)
    df["close"] = px["close"]
    df["ret"] = 100 * np.log(px["close"]).diff()
    if "high" in px and "low" in px:
        hl = np.log(px["high"] / px["low"])
        rv = 1e4 * hl ** 2 / (4 * np.log(2))
        df["rv"] = rv.where(hl > 0)  # 高値=安値の日や逆転は欠損扱い
    df = df.iloc[1:].dropna(subset=["ret"])
    if "rv" in df:
        df["rv"] = df["rv"].ffill()
    return df


def add_exog(df, driver):
    """先行市場のリターンを、対象日 t の寄り付き前に分かっている形で列に足す。

    x       : 対象日 t より前の日付で最新の先行市場の二乗リターン（%^2）
    xn      : そのリターンが負のときだけ x（下落の上乗せ用）
    x_next / xn_next : 次の対象日（行 t の翌営業日）向けの同じ値。予報時点で既知。
    """
    drv = driver[["ret"]].rename(columns={"ret": "dret"}).copy()
    drv["ddate"] = drv.index

    def asof(dates):
        left = pd.DataFrame({"date": pd.to_datetime(dates)})
        m = pd.merge_asof(left, drv, left_on="date", right_on="ddate",
                          direction="backward", allow_exact_matches=False)
        return m["dret"].to_numpy()

    cur = asof(df.index)
    nxt_dates = list(df.index[1:]) + [df.index[-1] + pd.offsets.BDay(1)]
    nxt = asof(nxt_dates)
    out = df.copy()
    for name, v in [("x", cur), ("x_next", nxt)]:
        v = np.nan_to_num(v, nan=0.0)
        out[name] = v ** 2
        out[name.replace("x", "xn", 1)] = np.where(v < 0, v ** 2, 0.0)
    return out


def load_returns(key, with_exog=True):
    from config import EXOG
    df = make_returns(load_prices(key))
    drv_key = EXOG.get(key)
    if with_exog and drv_key and (DATA_DIR / f"{drv_key}.csv").exists():
        df = add_exog(df, make_returns(load_prices(drv_key)))
    return df


def has_exog(df):
    return "x" in df and "x_next" in df


def has_range(df):
    """HAR-RVに使える高値・安値データがあるか。"""
    return "rv" in df and df["rv"].notna().mean() > 0.9


def write_web_data(name, var_name, payload):
    """表示ページ用に window.<var_name> = {...} 形式で書く（file://でも読めるように）。"""
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), **payload}
    text = f"window.{var_name} = " + json.dumps(payload, ensure_ascii=False, allow_nan=False) + ";\n"
    (WEB_DATA_DIR / name).write_text(text, encoding="utf-8")


def r(x, nd=4):
    """JSON用の丸め（NaNはNoneに）。"""
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), nd)
