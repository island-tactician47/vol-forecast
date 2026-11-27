"""① データ取得：config.TICKERS の日足を yfinance で取得し data/<キー>.csv に保存する。

yfinance が無い場合は  pip install yfinance  を実行するか、
data/ に自分でCSV（Date, Open, High, Low, Close など）を置けばよい。

- 失敗したら FETCH_RETRIES 回まで再試行する
- 取得したデータが手元のCSVより古い・短い場合は、上書きせず手元のCSVを残す（警告を出す）
- 一部の銘柄が失敗しても他は続ける。全部失敗したときだけ異常終了（GitHub Actions では「::warning::」の注釈になる）
"""
import sys
import time

import pandas as pd

from config import DATA_DIR, FETCH_RETRIES, START_DATE, TICKERS


def warn(msg):
    print(f"::warning::{msg}", flush=True)   # GitHub Actions ではこの行が警告として表示される


def download(yf, symbol):
    last = None
    for i in range(1, FETCH_RETRIES + 1):
        try:
            df = yf.download(symbol, start=START_DATE, auto_adjust=False, progress=False)
            if df is not None and not df.empty:
                return df
            last = "データが空でした"
        except Exception as e:  # 通信エラーなど
            last = str(e)
        if i < FETCH_RETRIES:
            print(f"  再試行 {i}/{FETCH_RETRIES - 1}（{last}）", flush=True)
            time.sleep(3 * i)
    raise RuntimeError(last or "取得できませんでした")


def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が入っていません。コマンドプロンプトで次を実行してください:")
        print("  pip install yfinance")
        print("または data/ フォルダに価格CSVを直接置いてください（data/README.txt 参照）。")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)
    ok = 0
    for key, (name, symbol) in TICKERS.items():
        print(f"{name}（{symbol}）を取得中...", flush=True)
        try:
            df = download(yf, symbol)
        except Exception as e:
            warn(f"{name}の取得に失敗しました: {e}（手元のデータをそのまま使います）")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
        df = df[cols].dropna()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "Date"

        path = DATA_DIR / f"{key}.csv"
        if path.exists():  # 取得し直したデータが手元より古い・短いときは上書きしない
            try:
                old = pd.read_csv(path, usecols=[0], parse_dates=[0])
                old_last, old_n = old.iloc[-1, 0], len(old)
                if df.index[-1] < old_last or len(df) < old_n - 5:
                    warn(f"{name}：取得したデータが手元より古い・短いので上書きしません"
                         f"（取得 {len(df)}行〜{df.index[-1].date()} ／ 手元 {old_n}行〜{old_last.date()}）")
                    continue
            except Exception:
                pass
        df.to_csv(path)
        ok += 1
        print(f"  {len(df)}行  {df.index[0].date()} 〜 {df.index[-1].date()}", flush=True)
    if ok == 0:
        print("1銘柄も取得できませんでした。")
        sys.exit(1)
    print("完了")


if __name__ == "__main__":
    main()
