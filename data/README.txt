このフォルダに価格のCSVを置きます（1銘柄1ファイル、ファイル名がキーになります）。

自動取得：ランチャーの「① データ取得」（yfinance が必要：pip install yfinance）
  取得する銘柄は config.py の TICKERS で変更できます。

手動で置く場合の形式（どれでも可）：
  - Date, Open, High, Low, Close （高値・安値があると HAR-RV モデルも使われます）
  - FREDのCSV（observation_date, SP500 など。欠損の "." は自動で除外）
  - 1列目が日付で、Close または 終値 の列があるもの

データが750営業日（約3年）未満の銘柄はスキップされます（config.py の MIN_DAYS）。
