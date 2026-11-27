"""① データ取得：config.TICKERS の日足を yfinance で取得し data/<キー>.csv に保存する。

yfinance が無い場合は  pip install yfinance  を実行するか、
data/ に自分でCSV（Date, Open, High, Low, Close など）を置けばよい。
"""
import sys

import pandas as pd

from config import DATA_DIR, START_DATE, TICKERS


def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が入っていません。コマンドプロンプトで次を実行してください:")
        print("  pip install yfinance")
        print("または data/ フォルダに価格CSVを直接置いてください（data/README.txt 参照）。")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)
    for key, (name, symbol) in TICKERS.items():
        print(f"{name}（{symbol}）を取得中...", flush=True)
        try:
            df = yf.download(symbol, start=START_DATE, auto_adjust=False, progress=False)
        except Exception as e:  # 通信エラーなど
            print(f"  失敗: {e}")
            continue
        if df is None or df.empty:
            print("  データが空でした（ティッカー名やネット接続を確認）")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
        df = df[cols].dropna()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "Date"
        df.to_csv(DATA_DIR / f"{key}.csv")
        print(f"  {len(df)}行  {df.index[0].date()} 〜 {df.index[-1].date()}", flush=True)
    print("完了")


if __name__ == "__main__":
    main()
