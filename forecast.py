"""② 予報：各銘柄のボラティリティを HORIZON 営業日先まで予測し、天気に変換して web/data/forecast.js に書く。
実行するたびに予報を results/archive/forecasts.csv に追記する（⑤ 答え合わせで使う）。

天気の決め方：MAIN_MODEL の予想ボラが、過去 LOOKBACK_YEARS 年の同モデルの
ボラの中で何パーセンタイルにあたるか（＝いつもと比べてどれくらい荒れそうか）。
「大荒れ確率」は、モデルの標準化残差の経験分布から |1日の変動| が「その銘柄の普段の1日の標準偏差の BIG_MOVE_MAIN 倍」
を超える確率（銘柄ごとに基準が違う。段階は BIG_MOVE_TIERS）。
予報の日付は、その市場の営業日（market_cal.py）。データが古いときは警告を付ける。
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import (ALERT_IDX, ALERT_PCT, BAND_COVERAGE, BIG_MOVE_MAIN, BIG_MOVE_PCT_BY_KEY, BIG_MOVE_TIERS, CANDLE_DAYS,
                    FX_BAR_COMPLETE_UTC_HOUR, FX_KEYS, HORIZON, LOOKBACK_YEARS, MAIN_MODEL, MAIN_MODEL_BY_KEY, MARKET_CAL, MIN_DAYS, RANGE_COVERAGE,
                    REALIZED_WINDOW, RESULT_DIR, STALE_WARN, WARNING_IDX, WARNING_PCT, TAIL_FLOOR, WEATHER, WEATHER_BY,
                    WEATHER_MOVE_BY_KEY, WEATHER_MOVE_MULT)
from config import EXOG
from data_io import display_name, list_datasets, load_prices, load_returns, r, write_web_data
from market_cal import last_open_on_or_before, next_days
import trend
from models import TRADING_DAYS, build_models

WEEKDAYS = "月火水木金土日"
ARCHIVE_FILE = RESULT_DIR / "archive" / "forecasts.csv"


def weather_index(pct):
    for i, (limit, *_rest) in enumerate(WEATHER):
        if pct < limit:
            return i
    return len(WEATHER) - 1


def weather_bounds(key, ret_sd):
    """天気（快晴・晴れ・くもり・雨・雷雨）の上限となる1日の値動き（%）の5つ。それ以上は台風。

    銘柄ごとに、普段の1日の標準偏差 ret_sd の倍数（WEATHER_MOVE_MULT）。0.05%刻みに丸める。
    WEATHER_MOVE_BY_KEY で銘柄ごとに決め打ちもできる。
    """
    fixed = WEATHER_MOVE_BY_KEY.get(key)
    if fixed:
        return [float(x) for x in fixed]
    return [round(m * ret_sd / 0.05) * 0.05 for m in WEATHER_MOVE_MULT]


def move_index(sigma, bounds):
    """予想の1日の値動き（σ、%）が、境界のどこに入るか（0=快晴 … 5=台風）。"""
    for i, b in enumerate(bounds):
        if sigma < b:
            return i
    return len(bounds)


def weather_of(pct, sigma=None, bounds=None):
    """天気。WEATHER_BY="move" なら σ と境界で、"percentile" なら順位 pct で決める。"""
    idx = move_index(sigma, bounds) if WEATHER_BY == "move" and sigma is not None else weather_index(pct)
    _, icon, label, desc = WEATHER[idx]
    return {"icon": icon, "label": label, "desc": desc, "idx": idx}


def alert_of(days):
    """予報期間中の最も荒れた日で、注意報・警報を決める。"""
    if WEATHER_BY == "move":
        worst = max(d["weather"]["idx"] for d in days)
        return "警報" if worst >= WARNING_IDX else "注意報" if worst >= ALERT_IDX else None
    pct_max = max(d["percentile"] for d in days)
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


def big_thresholds(key, ret_sd):
    """「大荒れ」の基準（1日の変動の%）。段階 {倍数: %} と、代表値の%。銘柄ごとの普段の標準偏差が単位。"""
    tiers = {m: round(m * ret_sd, 2) for m in BIG_MOVE_TIERS}
    main_pct = BIG_MOVE_PCT_BY_KEY.get(key) or round(BIG_MOVE_MAIN * ret_sd, 2)
    return tiers, main_pct


def make_days(main, df, path, fc, key=None):
    """基準日（df の最終日）時点の予報を作る。df・path は基準日までのデータだけを渡すこと。"""
    sig_hist = np.sqrt(path.dropna())
    lookback = sig_hist.iloc[-LOOKBACK_YEARS * TRADING_DAYS:].to_numpy()
    mu = main.mean() if hasattr(main, "mean") else 0.0
    z = ((df["ret"] - mu) / np.sqrt(path)).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    abs_z = np.abs(z[-LOOKBACK_YEARS * TRADING_DAYS:])
    abs_ret = df["ret"].abs().iloc[-LOOKBACK_YEARS * TRADING_DAYS:]
    tq = tail_quantiles(df, path, mu, len(fc))
    ret_sd = float(df["ret"].iloc[-LOOKBACK_YEARS * TRADING_DAYS:].std())
    tiers, big_pct = big_thresholds(key, ret_sd)
    bounds = weather_bounds(key, ret_sd)

    sig = np.sqrt(fc)
    cum_sd = np.sqrt(np.cumsum(fc))
    close = float(df["close"].iloc[-1])
    dates = next_days(df.index[-1], len(fc), MARKET_CAL.get(key))  # その市場の営業日（祝日を除く）
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
            "weather": weather_of(pct, sig[k], bounds),
            "big_pct": big_pct,  # 「大荒れ」とみなす1日の変動幅（%）。銘柄ごと
            "prob_big": r(float((abs_z > big_pct / sig[k]).mean() * 100), 0),
            "prob_big_clim": r(float((abs_ret > big_pct).mean() * 100), 0),  # 平年値（比較用）
            "prob_tiers": [{"mult": m, "pct": v, "prob": r(float((abs_z > v / sig[k]).mean() * 100), 0),
                            "clim": r(float((abs_ret > v).mean() * 100), 0)} for m, v in tiers.items()],
            "band95": r(tq[0][1] * sig[k], 3),  # その日1日の変動がこれを超えたら大外れ（95%）
            "move68": r(tq[0][0] * sig[k], 2),  # その日1日の値動き幅（3回に2回はこの中、±%）
            "range_low": r(close * np.exp(-q_range * cum_sd[k] / 100), 2),
            "range_high": r(close * np.exp(q_range * cum_sd[k] / 100), 2),
        })
    return days, lookback, sig_hist, tq[0][0]


def expected_last_date(key, today=None, now_utc=None):
    """今日の前日以前で最も新しい営業日。日足の最終日がこれより古ければ、更新が1営業日以上抜けている。

    24時間取引の銘柄（FX_KEYS）は、データ側が UTC 22時より前の「今日」の足を使わないので（data_io.drop_incomplete）、
    期待する日も「完成している最新の足」（UTC の日付。22時より前なら前日）にそろえる。
    """
    if key in FX_KEYS and today is None:
        now = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
        done = now.date() if now.hour >= FX_BAR_COMPLETE_UTC_HOUR else now.date() - pd.Timedelta(days=1).to_pytimedelta()
        return last_open_on_or_before(MARKET_CAL.get(key), pd.Timestamp(done))
    today = pd.Timestamp(today or datetime.now().date())
    return last_open_on_or_before(MARKET_CAL.get(key), today - pd.Timedelta(days=1))


def data_warnings(key, last_date, today=None):
    """データの鮮度の警告（文字列のリスト）。空なら問題なし。"""
    if not STALE_WARN:
        return []
    out = []
    exp = expected_last_date(key, today)
    if pd.Timestamp(last_date) < exp:
        out.append(f"{display_name(key)}のデータが古い可能性があります（最終 {pd.Timestamp(last_date):%m/%d}、期待 {exp:%m/%d} 以降）。")
    drv = EXOG.get(key)
    if drv:
        try:
            dl = load_prices(drv).index[-1]
            dexp = expected_last_date(drv, today)
            if dl < dexp:
                out.append(f"{display_name(key)}の予報に使う先行市場（{display_name(drv)}）のデータが古い可能性があります"
                           f"（最終 {dl:%m/%d}、期待 {dexp:%m/%d} 以降）。")
        except Exception:
            pass
    return out


def trend_of(df):
    """方向の見立て（k営業日後までに上がる確率）と、その当たり具合の検証。失敗しても予報本体は止めない。"""
    try:
        fc = trend.forecast_trend(df)
        ev = trend.evaluate(df)
    except Exception as e:
        print(f"  方向の見立てに失敗: {type(e).__name__}: {e}")
        return None
    days = [{"k": x["k"], "p_up": r(x["p_up"], 4), "base": r(x["base"], 4), **trend.label_of(x["p_up"], x["base"])} for x in fc]
    return {"days": days, "grade": trend.grade_of(ev), "band": trend.TREND_BAND,
            "eval": [{"k": k, **{c: (r(v, 4) if isinstance(v, float) else v) for c, v in e.items()}} for k, e in ev.items()]}


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
    days, lookback, sig_hist, q68 = make_days(main, df, path, fc, key)
    ret_sd = float(df["ret"].iloc[-LOOKBACK_YEARS * TRADING_DAYS:].std())
    bounds = weather_bounds(key, ret_sd)

    last_sig = float(sig_hist.iloc[-1])
    last_pct = float((lookback < last_sig).mean() * 100)
    px = load_prices(key).reindex(df.index)
    cs = df.index[-CANDLE_DAYS:]

    def col(name, idx):
        return [r(x, 2) for x in px[name].reindex(idx)] if name in px else None

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
                  "percentile": r(last_pct, 0), "weather": weather_of(last_pct, last_sig, bounds)},
        "alert": alert_of(days),
        "weather_scale": {"by": WEATHER_BY, "ret_sd": r(ret_sd, 3), "bounds": [r(b, 2) for b in bounds]},
        "days": days,
        "comparison": comparison,
        "params": {k: r(v, 5) for k, v in main.info().items()} if hasattr(main, "info") else None,
        "exog": EXOG.get(key),
        "history": {  # チャート用（全期間）。ボラは % / 日
            "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "close": [r(x, 2) for x in df["close"]],
            "abs_ret": [r(abs(x), 2) for x in df["ret"]],
            "sigma": [r(x, 2) for x in np.sqrt(path)],
            "realized": [r(x, 2) for x in realized_centered(df["ret"])],
            "candle_from": len(df) - len(cs),  # ここから先は始値・高値・安値あり
            "open": col("open", cs), "high": col("high", cs), "low": col("low", cs),
        },
        "n_days": len(df),
        "big": {"main_mult": BIG_MOVE_MAIN, "main_pct": days[0]["big_pct"]},
        "warnings": data_warnings(key, df.index[-1]),
        "trend": trend_of(df),   # 方向の見立て。ボラの予報とは別ページ（trend.js）に書くため、main() で取り出す
    }
    if item["trend"]:  # 日付は予報の日付（営業日）にそろえる
        for t, d in zip(item["trend"]["days"], days):
            t["date"], t["weekday"] = d["date"], d["weekday"]
    d1 = days[0]
    print(f"  明日: {d1['weather']['icon']} {d1['weather']['label']}"
          f"（1日 ±{d1['move68']}%、予想σ {d1['sigma_daily']}%、過去{LOOKBACK_YEARS}年の{d1['percentile']:.0f}%点）"
          + (f"  【{item['alert']}】" if item["alert"] else ""), flush=True)
    for w in item["warnings"]:
        print(f"  警告: {w}", flush=True)
    return item


def archive_rows(key, model, base_date, base_close, days, source):
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return [{"run_at": run_at, "source": source, "key": key, "model": model,
             "base_date": base_date, "base_close": base_close, "k": d["k"],
             "target_date_est": d["date_iso"], "sigma_daily": d["sigma_daily"],
             "percentile": d["percentile"], "weather_idx": d["weather"]["idx"],
             "prob_big": d["prob_big"], "prob_big_clim": d["prob_big_clim"], "band95": d["band95"],
             "big_pct": d.get("big_pct"),
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

    trend_items = [{"key": it["key"], "name": it["name"], "last_date": it["last_date"], "last_close": it["last_close"],
                    "trend": it.pop("trend", None)} for it in items]   # 方向の見立ては forecast.js に入れず、別ページ用に分ける
    write_web_data("trend.js", "TREND", {"horizon": HORIZON, "band": trend.TREND_BAND, "items": trend_items})
    write_web_data("forecast.js", "FORECAST", {
        "horizon": HORIZON, "main_model": MAIN_MODEL, "lookback_years": LOOKBACK_YEARS,
        "big_move_mult": BIG_MOVE_MAIN, "big_move_tiers": list(BIG_MOVE_TIERS), "weather_by": WEATHER_BY,
        "weather": [{"icon": w[1], "label": w[2]} for w in WEATHER],
        "realized_window": REALIZED_WINDOW, "warnings": [w for it in items for w in it["warnings"]], "items": items,
    })
    save_archive(items)
    print(f"完了：{len(items)}銘柄。ランチャーの「予報ページ」で表示できます。")


if __name__ == "__main__":
    main()
