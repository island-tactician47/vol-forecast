"""④ 自己相関：リターン r、|r|、r² の自己相関を計算し web/data/acf.js に書く。

r の自己相関はほぼ0（方向は読めない）なのに、|r| と r² は正の相関が長く続く
（ボラティリティ・クラスタリング）ことを確かめるためのページ。
"""
import numpy as np

from config import ACF_MAX_LAG
from data_io import display_name, list_datasets, load_returns, r, write_web_data


def acf(x, max_lag):
    x = np.asarray(x, float)
    x = x - x.mean()
    denom = x @ x
    return [float(x[k:] @ x[:-k] / denom) for k in range(1, max_lag + 1)]


def main():
    keys = list_datasets()
    if not keys:
        print("data/ にCSVがありません。先に ① データ取得 を実行してください。")
        return
    items = []
    for key in keys:
        ret = load_returns(key)["ret"].to_numpy()
        res = {"r": acf(ret, ACF_MAX_LAG), "abs": acf(np.abs(ret), ACF_MAX_LAG),
               "sq": acf(ret ** 2, ACF_MAX_LAG)}
        items.append({"key": key, "name": display_name(key), "n": len(ret),
                      "band": r(1.96 / np.sqrt(len(ret)), 4),
                      **{k: [r(v, 4) for v in vals] for k, vals in res.items()}})
        print(f"{display_name(key)}: lag1  r={res['r'][0]:+.3f}  |r|={res['abs'][0]:+.3f}  "
              f"lag20 |r|={res['abs'][19]:+.3f}", flush=True)
    write_web_data("acf.js", "ACF", {"max_lag": ACF_MAX_LAG, "items": items})
    print("完了。ランチャーの「自己相関ページ」で表示できます。")


if __name__ == "__main__":
    main()
