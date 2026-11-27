"""⑤ 答え合わせ：過去の予報と実際の値動きを突き合わせ、web/data/archive.js に書く。

予報の出どころは2種類:
  実予報：forecast.py を実行するたびに results/archive/forecasts.csv に貯まった予報
  再現  ：まだ貯まっていない期間を補うため、各時点で「その日までのデータだけ」で
          推定・予報し直したもの（ウォークフォワード。BACKFILL_DAYS 日分）

突き合わせは「基準日から k 営業日後」のデータ行で行う（祝日でずれない）。
実際の天気は、実際の|変動|が過去の|変動|の何%点だったかで決める。
「大荒れ」の基準（big_pct）は予報した時点のものを行ごとに記録し、採点でもそれを使う
（古い記録で big_pct が無いものは旧方式の固定 BIG_MOVE_PCT）。
再現に失敗した銘柄があれば、警告（Actions の注釈）を出してページにも表示する（黙って実予報だけにはしない）。
直近の的中率は web/data/track.js に書き、週間予報ページの「信頼度」に使う。
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
            days, _, _, _ = make_days(m, sub, path_all.iloc[:t + 1], m.forecast(sub, HORIZON), key)
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
        bp = getattr(row, "big_pct", None)
        bp = BIG_MOVE_PCT if bp is None or not np.isfinite(bp) else float(bp)  # 古い記録は旧方式の固定値
        rec = {"s": 0 if row.source == "実予報" else 1, "b": row.base_date, "k": int(row.k), "bp": bp,
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


TRACK_DAYS = 250   # 信頼度に使う直近の件数（営業日）


def track_of(rows):
    """直近の的中率（k=1..HORIZON）。予想レンジに収まった割合・大外れ（95%ライン超え）の割合・信頼度の目安。"""
    out = {}
    for k in range(1, HORIZON + 1):
        done = [x for x in rows if x["k"] == k and x["ar"] is not None][-TRACK_DAYS:]
        if len(done) < 30:
            continue
        hit = float(np.mean([x["lo"] <= x["cl"] <= x["hi"] for x in done]) * 100)
        band = lambda x: x["b9"] if x["b9"] is not None else 1.96 * x["sg"]
        exc = float(np.mean([abs(x["ar"]) > band(x) for x in done]) * 100)
        dev = abs(hit - 68.3) + 2 * abs(exc - 5.0)   # 理想（68%・5%）からのずれ。大外れの方を重く見る
        grade = "◎" if dev <= 5 else "○" if dev <= 12 else "△"
        out[str(k)] = {"n": len(done), "range_hit": r(hit, 0), "exceed": r(exc, 1), "grade": grade,
                       "live": int(sum(1 for x in done if x["s"] == 0))}
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

    items, backfill_all, warnings = [], [], []
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
                msg = f"{display_name(key)}：過去データからの再現予報を作れませんでした（{type(e).__name__}: {e}）。実予報だけで採点しています。"
                print(f"::warning::{msg}", flush=True)
                warnings.append(msg)
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
        "weather": [{"icon": w[1], "label": w[2]} for w in WEATHER], "warnings": warnings, "items": items,
    })
    write_web_data("track.js", "TRACK", {"window": TRACK_DAYS, "items": {it["key"]: track_of(it["rows"]) for it in items}})
    print("完了。ランチャーの「答え合わせページ」で表示できます。")
    if warnings:  # 異常終了にはしない（後ろの工程＝予報の公開まで止まってしまうため）。警告とページのバナーで気づけるようにする
        print(f"警告：{len(warnings)} 銘柄で再現予報を作れませんでした。")


if __name__ == "__main__":
    main()
