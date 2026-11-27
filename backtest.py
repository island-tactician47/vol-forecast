"""③ 検証：直近 TEST_YEARS 年で、各モデルの1日先予測の精度を比べる。

- 拡大窓で REFIT_DAYS ごとに再推定（未来の情報は使わない）
- 損失関数：QLIKE（log h + r²/h）と MSE（r² - h）²。代理変数 r² がノイジーでも
  モデルの順位づけが歪まない損失（Patton 2011）。小さいほど良い。
- 95%区間の外れ率（理想は5%）：天気予報の「当たり具合」に相当
- BENCHMARK との差の Diebold-Mariano 検定（Newey-West）
- 事前固定の合格基準（config.ACCEPT_WIN_RATIO）で判定し、試行を results/backtest_log.csv に記録
"""
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import (ACCEPT_WIN_RATIO, BENCHMARK, DM_LAG, LOOKBACK_YEARS, MAIN_MODEL, MIN_DAYS, REFIT_DAYS,
                    RESULT_DIR, TEST_YEARS)
from data_io import display_name, list_datasets, load_returns, r, write_web_data
from forecast import realized_centered
from models import TRADING_DAYS, build_models

CHART_DAYS = 250


def dm_test(d, lag):
    """損失差 d の平均が0かを検定（Newey-West分散）。負なら比較モデルの方が良い。"""
    d = d[np.isfinite(d)]
    T = len(d)
    u = d - d.mean()
    var = u @ u / T
    for k in range(1, lag + 1):
        var += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / T
    if var <= 0:
        return np.nan, np.nan
    stat = d.mean() / np.sqrt(var / T)
    return stat, 2 * (1 - norm.cdf(abs(stat)))


def backtest_one(key):
    df = load_returns(key)
    n = len(df)
    start = max(n - TEST_YEARS * TRADING_DAYS, MIN_DAYS)
    if start >= n - 50:
        print(f"  データ不足でスキップ（{n}日）")
        return None

    preds, q95s = {}, {}
    for b in range(start, n, REFIT_DAYS):
        e = min(b + REFIT_DAYS, n)
        for m in build_models(df, 1):
            try:
                m.fit(df.iloc[:b])
                p_all = m.one_step(df.iloc[:e])
                p = p_all.iloc[b:e]
                # 学習期間の標準化残差から95%点を求める（正規分布の1.96の代わり）
                mu = m.mean() if hasattr(m, "mean") else 0.0
                z = ((df["ret"].iloc[:b] - mu) / np.sqrt(p_all.iloc[:b])).abs()
                z = z.replace([np.inf, -np.inf], np.nan).dropna().iloc[-LOOKBACK_YEARS * TRADING_DAYS:]
                q95 = pd.Series(float(z.quantile(0.95)), index=p.index)
            except Exception as ex:
                print(f"  {m.name} 失敗: {ex}")
                continue
            preds.setdefault(m.name, []).append(p)
            q95s.setdefault(m.name, []).append(q95)
    preds = {k: pd.concat(v) for k, v in preds.items()}
    q95s = {k: pd.concat(v) for k, v in q95s.items()}

    test = df.iloc[start:]
    r2 = (test["ret"] ** 2).to_numpy()
    losses, rows = {}, []
    for name, p in preds.items():
        h = p.reindex(test.index).to_numpy()
        ok = np.isfinite(h) & (h > 0)
        ql = np.where(ok, np.log(np.where(ok, h, 1)) + r2 / np.where(ok, h, 1), np.nan)
        mse = np.where(ok, (r2 - h) ** 2, np.nan)
        losses[name] = ql
        rows.append({"model": name, "qlike": np.nanmean(ql), "mse": np.nanmean(mse),
                     "miss95": np.nanmean(np.where(ok, np.abs(test["ret"].to_numpy()) > 1.96 * np.sqrt(np.where(ok, h, 1)), np.nan)) * 100,
                     "miss95_emp": np.nanmean(np.where(ok, np.abs(test["ret"].to_numpy()) > q95s[name].reindex(test.index).to_numpy() * np.sqrt(np.where(ok, h, 1)), np.nan)) * 100})
    bench = losses.get(BENCHMARK)
    for row in rows:
        if bench is not None and row["model"] != BENCHMARK:
            row["dm_stat"], row["dm_p"] = dm_test(losses[row["model"]] - bench, DM_LAG)
        else:
            row["dm_stat"], row["dm_p"] = np.nan, np.nan
    rows.sort(key=lambda x: x["qlike"])

    q = {row["model"]: row["qlike"] for row in rows}
    win = MAIN_MODEL in q and BENCHMARK in q and q[MAIN_MODEL] < q[BENCHMARK]
    for row in rows:
        print(f"  {row['model']:<10} QLIKE {row['qlike']:.4f}  外れ率 正規{row['miss95']:.1f}% 実績分布{row['miss95_emp']:.1f}%"
              + (f"  DM {row['dm_stat']:+.2f} (p={row['dm_p']:.3f})" if np.isfinite(row["dm_stat"]) else ""))

    chart = test.iloc[-CHART_DAYS:]
    return {
        "key": key, "name": display_name(key),
        "test_start": test.index[0].strftime("%Y-%m-%d"), "test_end": test.index[-1].strftime("%Y-%m-%d"),
        "n_test": len(test), "main_wins": bool(win),
        "rows": [{k: (r(v, 4) if isinstance(v, (float, np.floating)) else v) for k, v in row.items()} for row in rows],
        "chart": {
            "dates": [d.strftime("%Y-%m-%d") for d in chart.index],
            "abs_ret": [r(abs(x), 3) for x in chart["ret"]],
            "realized": [r(x, 3) for x in realized_centered(df["ret"]).reindex(chart.index)],
            "series": {name: [r(np.sqrt(x), 3) if x and x > 0 else None for x in p.reindex(chart.index)]
                       for name, p in preds.items()},
        },
    }


def main():
    keys = list_datasets()
    if not keys:
        print("data/ にCSVがありません。先に ① データ取得 を実行してください。")
        return
    items = []
    for key in keys:
        print(f"{display_name(key)} を検証中...", flush=True)
        try:
            it = backtest_one(key)
        except Exception as e:
            print(f"  エラー: {e}")
            it = None
        if it:
            items.append(it)
    if not items:
        return

    wins = sum(it["main_wins"] for it in items)
    ratio = wins / len(items)
    passed = ratio >= ACCEPT_WIN_RATIO
    verdict = (f"{MAIN_MODEL} が {BENCHMARK} に勝った銘柄：{wins}/{len(items)}"
               f"（基準 {ACCEPT_WIN_RATIO:.0%} 以上）→ {'合格' if passed else '不合格'}")
    print(verdict)

    write_web_data("backtest.js", "BACKTEST", {
        "main_model": MAIN_MODEL, "benchmark": BENCHMARK, "test_years": TEST_YEARS,
        "refit_days": REFIT_DAYS, "verdict": verdict, "passed": passed, "items": items,
    })
    RESULT_DIR.mkdir(exist_ok=True)
    pd.DataFrame([{"銘柄": it["name"], **row} for it in items for row in it["rows"]]).to_csv(
        RESULT_DIR / f"backtest_{datetime.now():%Y%m%d_%H%M}.csv", index=False, encoding="utf-8-sig")
    log = RESULT_DIR / "backtest_log.csv"  # 試行回数の記録
    pd.DataFrame([{"日時": datetime.now().strftime("%Y-%m-%d %H:%M"), "主モデル": MAIN_MODEL,
                   "基準": BENCHMARK, "検証年数": TEST_YEARS, "再推定間隔": REFIT_DAYS,
                   "銘柄数": len(items), "勝ち": wins, "合格": passed}]).to_csv(
        log, mode="a", header=not log.exists(), index=False, encoding="utf-8-sig")
    print(f"完了。試行ログ：{log.name}（これまで {len(pd.read_csv(log, encoding='utf-8-sig'))} 回）")


if __name__ == "__main__":
    main()
