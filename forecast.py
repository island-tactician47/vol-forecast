"""② 予報：各銘柄のボラティリティを HORIZON 営業日先まで予測し、天気に変換して web/data/forecast.js に書く。
実行するたびに予報を results/archive/forecasts.csv に追記する（⑤ 答え合わせで使う）。

天気の決め方：MAIN_MODEL の予想ボラが、過去 LOOKBACK_YEARS 年の同モデルの
ボラの中で何パーセンタイルにあたるか（＝いつもと比べてどれくらい荒れそうか）。
「大荒れ確率」は、モデルの標準化残差の経験分布から |1日の変動| > BIG_MOVE_PCT となる確率。
"""
from datetime import datetime

import numpy as np
import pandas as pd

from config import (ALERT_PCT, BAND_COVERAGE, BIG_MOVE_PCT, HISTORY_DAYS, HORIZON, LOOKBACK_YEARS,
                    MAIN_MODEL, MAIN_MODEL_BY_KEY, MIN_DAYS, RANGE_COVERAGE, REALIZED_WINDOW, RESULT_DIR, WARNING_PCT,
                    TAIL_FLOOR, WEATHER)
from config import EXOG
from data_io import display_name, list_datasets, load_returns, r, write_web_data
from models import TRADING_DAYS, build_models

WEEKDAYS = "月火水木金土日"
ARCHIVE_FILE = RESULT_DIR / "archive" / "forecasts.csv"


def weather_index(pct):
    for i, (limit, *_rest) in enumerate(WEATHER):
        if pct < limit:
            return i
    return len(WEATHER) - 1


def weather_of(pct):
    _, icon, label, desc = WEATHER[weather_index(pct)]
    return {"icon": icon, "label": label, "desc": desc, "idx": weather_index(pct)}


def alert_of(pct_max):
    if pct_max >= WARNING_PCT:
        return "警報"
    if pct_max >= ALERT_PCT:
        return "注意報"
    return None


def realized_centered(ret, window=REALIZED_WINDOW):
    """後から見た「実際の荒れ具合」：前後 window 日の二乗リターン平均の平方根（%）。"""
    return np.sqrt((ret ** 2).rolling(window, center=True, min_periods=max(3, window // 4)).mean())


def tail_quantiles(df, path, mu, h):
    """k日間の累積リターンを予想σで標準化した値の、絶対値の分位点（k=1..h）。

    正規分布なら RANGE_COVERAGE→1.0、BAND_COVERAGE→1.96 になるところを、
    実績の分布（裾が厚い・モデルの誤差も含む）から求める。
    """
    L = LOOKBACK_YEARS * TRADING_DAYS
    e = (df["ret"] - mu).iloc[-L:]
    v = path.reindex(e.index)
    out = []
    for k in range(1, h + 1):
        z = (e.rolling(k).sum() / np.sqrt(v.rolling(k).sum())).abs()
        z = z.replace([np.inf, -np.inf], np.nan).dropna()
        q1, q2 = float(z.quantile(RANGE_COVERAGE)), float(z.quantile(BAND_COVERAGE))
        if TAIL_FLOOR:  # 学習期間内の残差は小さめに出るので、正規分布より狭くはしない
            q1, q2 = max(q1, 1.0), max(q2, 1.96)
        out.append((q1, q2))
    return out


def make_days(main, df, path, fc):
    """基準日（df の最終日）時点の予報を作る。df・path は基準日までのデータだけを渡すこと。"""
    sig_hist = np.sqrt(path.dropna())
    lookback = sig_hist.iloc[-LOOKBACK_YEARS * TRADING_DAYS:].to_numpy()
    mu = main.mean() if hasattr(main, "mean") else 0.0
    z = ((df["ret"] - mu) / np.sqrt(path)).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    abs_z = np.abs(z[-LOOKBACK_YEARS * TRADING_DAYS:])
    abs_ret = df["ret"].abs().iloc[-LOOKBACK_YEARS * TRADING_DAYS:]
    tq = tail_quantiles(df, path, mu, len(fc))

    sig = np.sqrt(fc)
    cum_sd = np.sqrt(np.cumsum(fc))
    close = float(df["close"].iloc[-1])
    dates = pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=len(fc))  # 祝日は未考慮
    days = []
    for k in range(len(fc)):
        pct = float((lookback < sig[k]).mean() * 100)
        q_range = tq[k][0]
        days.append({
            "k": k + 1,
            "date_iso": dates[k].strftime("%Y-%m-%d"),
            "date": dates[k].strftime("%m/%d"),
            "weekday": WEEKDAYS[dates[k].weekday()],
            "sigma_daily": r(sig[k], 3),
            "vol_ann": r(sig[k] * np.sqrt(TRADING_DAYS), 1),
            "percentile": r(pct, 0),
            "weather": weather_of(pct),
            "prob_big": r(float((abs_z > BIG_MOVE_PCT / sig[k]).mean() * 100), 0),
            "prob_big_clim": r(float((abs_ret > BIG_MOVE_PCT).mean() * 100), 0),  # 平年値（比較用）
            "band95": r(tq[0][1] * sig[k], 3),  # その日1日の変動がこれを超えたら大外れ（95%）
            "move68": r(tq[0][0] * sig[k], 2),  # その日1日の値動き幅（3回に2回はこの中、±%）
            "range_low": r(close * np.exp(-q_range * cum_sd[k] / 100), 2),
            "range_high": r(close * np.exp(q_range * cum_sd[k] / 100), 2),
        })
    return days, lookback, sig_hist, tq[0][0]


def fit_models(df):
    fitted = {}
    for m in build_models(df, HORIZON):
        try:
            m.fit(df)
            fitted[m.name] = (m, m.forecast(df, HORIZON), m.one_step(df))
        except Exception as e:
            print(f"  {m.name} は失敗: {e}")
    return fitted


def forecast_one(key):
    df = load_returns(key)
    if len(df) < MIN_DAYS:
        print(f"  データが {len(df)} 日しかないのでスキップ（MIN_DAYS={MIN_DAYS}）")
        return None
    fitted = fit_models(df)
    if not fitted:
        return None
    want = MAIN_MODEL_BY_KEY.get(key, MAIN_MODEL)
    main_name = want if want in fitted else next(iter(fitted))
    main, fc, path = fitted[main_name]
    days, lookback, sig_hist, q68 = make_days(main, df, path, fc)

    last_sig = float(sig_hist.iloc[-1])
    last_pct = float((lookback < last_sig).mean() * 100)
    hist = df.iloc[-HISTORY_DAYS:]
    comparison = [{"model": n, "move68_day1": r(q68 * np.sqrt(f[0]), 2), "vol_ann_day1": r(np.sqrt(f[0]) * np.sqrt(TRADING_DAYS), 1),
                   "vol_ann_avg": r(np.sqrt(f.mean()) * np.sqrt(TRADING_DAYS), 1)}
                  for n, (_, f, _) in fitted.items()]
    item = {
        "key": key,
        "name": display_name(key),
        "model": main_name,
        "last_date": df.index[-1].strftime("%Y-%m-%d"),
        "last_close": r(float(df["close"].iloc[-1]), 2),
        "last_return": r(float(df["ret"].iloc[-1]), 2),
        "today": {"sigma_daily": r(last_sig, 3), "vol_ann": r(last_sig * np.sqrt(TRADING_DAYS), 1),
                  "move68": r(q68 * last_sig, 2),
                  "percentile": r(last_pct, 0), "weather": weather_of(last_pct)},
        "alert": alert_of(max(d["percentile"] for d in days)),
        "days": days,
        "comparison": comparison,
        "params": {k: r(v, 5) for k, v in main.info().items()} if hasattr(main, "info") else None,
        "exog": EXOG.get(key),
        "history": {
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "abs_ret": [r(abs(x), 3) for x in hist["ret"]],
            "sigma": [r(x, 3) for x in np.sqrt(path.reindex(hist.index))],
            "realized": [r(x, 3) for x in realized_centered(df["ret"]).reindex(hist.index)],
        },
        "n_days": len(df),
    }
    d1 = days[0]
    print(f"  明日: {d1['weather']['icon']} {d1['weather']['label']}"
          f"（1日 ±{d1['move68']}%、過去{LOOKBACK_YEARS}年の{d1['percentile']:.0f}%点）"
          + (f"  【{item['alert']}】" if item["alert"] else ""), flush=True)
    return item


def archive_rows(key, model, base_date, base_close, days, source):
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return [{"run_at": run_at, "source": source, "key": key, "model": model,
             "base_date": base_date, "base_close": base_close, "k": d["k"],
             "target_date_est": d["date_iso"], "sigma_daily": d["sigma_daily"],
             "percentile": d["percentile"], "weather_idx": d["weather"]["idx"],
             "prob_big": d["prob_big"], "prob_big_clim": d["prob_big_clim"], "band95": d["band95"],
             "range_low": d["range_low"], "range_high": d["range_high"]} for d in days]


def read_archive():
    """予報アーカイブを読む。列数の違う行（旧形式）が混ざっていても読めるようにする。"""
    import csv
    with open(ARCHIVE_FILE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return pd.DataFrame()
    header, body = rows[0], rows[1:]
    width = max(len(header), *(len(b) for b in body)) if body else len(header)
    if width > len(header):  # 旧ヘッダのまま新しい列が追記された場合
        header = header + ["band95"] + [f"extra{i}" for i in range(width - len(header) - 1)]
    body = [b + [""] * (width - len(b)) for b in body]
    df = pd.DataFrame(body, columns=header)
    for c in df.columns:
        if c not in ("run_at", "source", "key", "model", "base_date", "target_date_est"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def save_archive(items):
    rows = []
    for it in items:
        rows += archive_rows(it["key"], it["model"], it["last_date"], it["last_close"], it["days"], "実予報")
    if not rows:
        return
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows)
    if ARCHIVE_FILE.exists():  # 列が増えても壊れないよう、読み込んで結合してから書き直す
        new = pd.concat([read_archive(), new], ignore_index=True)
    new.to_csv(ARCHIVE_FILE, index=False, encoding="utf-8-sig")
    print(f"予報をアーカイブに保存しました（{ARCHIVE_FILE.relative_to(RESULT_DIR.parent)}）")


def main():
    keys = list_datasets()
    if not keys:
        print("data/ にCSVがありません。先に ① データ取得 を実行してください。")
        return
    items = []
    for key in keys:
        print(f"{display_name(key)} を計算中...", flush=True)
        try:
            item = forecast_one(key)
        except Exception as e:
            print(f"  エラー: {e}")
            item = None
        if item:
            items.append(item)

    write_web_data("forecast.js", "FORECAST", {
        "horizon": HORIZON, "main_model": MAIN_MODEL, "lookback_years": LOOKBACK_YEARS,
        "big_move_pct": BIG_MOVE_PCT, "realized_window": REALIZED_WINDOW, "items": items,
    })
    save_archive(items)
    print(f"完了：{len(items)}銘柄。ランチャーの「予報ページ」で表示できます。")


if __name__ == "__main__":
    main()
