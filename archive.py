"""⑤ 答え合わせ：過去の予報と実際の値動きを突き合わせ、web/data/archive.js に書く。

予報の出どころは2種類:
  実予報：forecast.py を実行するたびに results/archive/forecasts.csv に貯まった予報
  再現  ：まだ貯まっていない期間を補うため、各時点で「その日までのデータだけ」で
          推定・予報し直したもの（ウォークフォワード。BACKFILL_DAYS 日分）

突き合わせは「基準日から k 営業日後」のデータ行で行う（祝日でずれない）。
実際の天気は、実際の|変動|が過去の|変動|の何%点だったかで決める。
"""
import numpy as np
import pandas as pd

from config import (BACKFILL_DAYS, BIG_MOVE_PCT, HORIZON, LOOKBACK_YEARS, MAIN_MODEL, MAIN_MODEL_BY_KEY,
                    MIN_DAYS, REFIT_DAYS, RESULT_DIR, WEATHER)
from data_io import display_name, list_datasets, load_returns, r, write_web_data
from forecast import ARCHIVE_FILE, archive_rows, make_days, read_archive, weather_index
from models import TRADING_DAYS, build_models

BACKFILL_FILE = RESULT_DIR / "archive" / "backfill.csv"


def backfill(key, df):
    """各基準日 t について、t までのデータだけで予報を作り直す。"""
    n = len(df)
    start = max(n - BACKFILL_DAYS, MIN_DAYS)
    rows = []
    for b in range(start, n, REFIT_DAYS):
        e = min(b + REFIT_DAYS, n)
        models = {m.name: m for m in build_models(df, HORIZON)}
        m = models.get(MAIN_MODEL_BY_KEY.get(key, MAIN_MODEL)) or next(iter(models.values()))
        m.fit(df.iloc[:b])                      # 基準日 b-1 までで推定
        path_all = m.one_step(df.iloc[:e])
        for t in range(b - 1, min(e, n - 1)):    # 基準日 t（翌日以降の実績が1日以上ある日）
            sub = df.iloc[:t + 1]
            days, _, _ = make_days(m, sub, path_all.iloc[:t + 1], m.forecast(sub, HORIZON))
            rows += archive_rows(key, m.name, sub.index[-1].strftime("%Y-%m-%d"),
                                 r(float(sub["close"].iloc[-1]), 2), days, "再現")
    return rows


def score(fc, df):
    """予報の各行に実績をつける（未到来なら実績は空）。"""
    dates = df.index
    abs_ret = df["ret"].abs().to_numpy()
    L = LOOKBACK_YEARS * TRADING_DAYS
    out = []
    for row in fc.itertuples(index=False):
        bi = dates.searchsorted(pd.Timestamp(row.base_date), side="right") - 1
        ti = bi + int(row.k)
        rec = {"s": 0 if row.source == "実予報" else 1, "b": row.base_date, "k": int(row.k),
               "sg": row.sigma_daily, "pf": int(row.weather_idx), "pp": row.percentile,
               "pb": row.prob_big, "cb": row.prob_big_clim, "lo": row.range_low, "hi": row.range_high,
               "b9": r(getattr(row, "band95", None), 3),
               "t": row.target_date_est, "ar": None, "cl": None, "aw": None, "ap": None}
        if bi >= 0 and ti < len(df):
            past = abs_ret[max(0, bi - L + 1):bi + 1]
            pct = float((past < abs_ret[ti]).mean() * 100)
            rec.update({"t": dates[ti].strftime("%Y-%m-%d"), "ar": r(float(df["ret"].iloc[ti]), 3),
                        "cl": r(float(df["close"].iloc[ti]), 2), "aw": weather_index(pct), "ap": r(pct, 0)})
        out.append(rec)
    return out


def main():
    keys = list_datasets()
    if not keys:
        print("data/ にCSVがありません。先に ① データ取得 を実行してください。")
        return
    live = read_archive() if ARCHIVE_FILE.exists() else pd.DataFrame()
    if not live.empty:  # 同じ基準日に何度も実行した場合は最後の予報を採用
        live = live.drop_duplicates(["key", "base_date", "k"], keep="last")
    print(f"実予報のアーカイブ：{len(live)} 件")

    items, backfill_all = [], []
    for key in keys:
        df = load_returns(key)
        if len(df) < MIN_DAYS:
            continue
        print(f"{display_name(key)} を答え合わせ中...", flush=True)
        parts = []
        if not live.empty and (live["key"] == key).any():
            parts.append(live[live["key"] == key])
        if BACKFILL_DAYS > 0:
            try:
                bf = pd.DataFrame(backfill(key, df))
                backfill_all.append(bf)
                parts.append(bf)
            except Exception as e:
                print(f"  再現に失敗: {e}")
        if not parts:
            continue
        rows = score(pd.concat(parts, ignore_index=True), df)
        rows.sort(key=lambda x: (x["b"], x["k"], x["s"]))
        done = [x for x in rows if x["ar"] is not None and x["k"] == 1]
        if done:
            hit = np.mean([x["lo"] <= x["cl"] <= x["hi"] for x in done]) * 100
            print(f"  1日先：{len(done)}件　レンジ的中 {hit:.0f}%（理想68%）　"
                  f"天気±1段階 {np.mean([abs(x['pf'] - x['aw']) <= 1 for x in done]) * 100:.0f}%", flush=True)
        items.append({"key": key, "name": display_name(key), "rows": rows})

    if backfill_all:
        BACKFILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(backfill_all).to_csv(BACKFILL_FILE, index=False, encoding="utf-8-sig")
    write_web_data("archive.js", "ARCHIVE", {
        "horizon": HORIZON, "big_move_pct": BIG_MOVE_PCT, "main_model": MAIN_MODEL,
        "weather": [{"icon": w[1], "label": w[2]} for w in WEATHER], "items": items,
    })
    print("完了。ランチャーの「答え合わせページ」で表示できます。")


if __name__ == "__main__":
    main()
