"""設定ファイル。挙動を変えたいときはまずここを書き換える。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"            # 価格CSVの置き場（1銘柄1ファイル）
RESULT_DIR = BASE_DIR / "results"       # CSVの結果・試行ログ
WEB_DIR = BASE_DIR / "web"
WEB_DATA_DIR = WEB_DIR / "data"         # 表示ページが読む data/*.js

# ---- データ取得（data_fetch.py / yfinance） -------------------------------
# ファイル名(キー) : (表示名, Yahoo!ファイナンスのティッカー)
TICKERS = {
    "N225":   ("日経平均", "^N225"),
    "SP500":  ("S&P500", "^GSPC"),
    "NDX":    ("NASDAQ100", "^NDX"),
    "SOX":    ("フィラデルフィア半導体", "^SOX"),
    "USDJPY": ("ドル円", "JPY=X"),
}
START_DATE = "2005-01-01"
# data/ に自分で置いたCSV（FREDのSP500.csv など）も自動で対象になる。

# ---- 予報（forecast.py） ----------------------------------------------------
HORIZON = 5                 # 何営業日先まで予報するか（週間予報）
MAIN_MODEL = "GJR-GARCH"    # 天気の判定に使うモデル名（models.py の name）
LOOKBACK_YEARS = 10         # 「いつもと比べてどうか」を測る比較期間
BIG_MOVE_PCT = 2.0          # 「大荒れ」とみなす1日の変動幅（%、絶対値）
HISTORY_DAYS = 120          # ページに描く過去の日数
MIN_DAYS = 750              # これ未満のデータ数の銘柄はスキップ

# 予想ボラの「過去比パーセンタイル」→ 天気。上から順に判定（pct < 上限）
WEATHER = [
    # 上限pct, アイコン, 天気, ひとこと
    (20,  "☀️", "快晴", "とても穏やか"),
    (40,  "🌤️", "晴れ", "穏やか"),
    (60,  "⛅", "くもり", "平常運転"),
    (80,  "🌧️", "雨", "やや荒れ模様"),
    (95,  "⛈️", "雷雨", "荒れ模様"),
    (101, "🌀", "台風", "大荒れ"),
]
ALERT_PCT = 80      # 予報期間中にこれ以上 → 注意報
WARNING_PCT = 95    # これ以上 → 警報

# ---- 検証（backtest.py） ----------------------------------------------------
TEST_YEARS = 3          # 直近何年を検証期間にするか
REFIT_DAYS = 250        # 何営業日ごとにパラメータを推定し直すか（拡大窓）
BENCHMARK = "EWMA"      # 比較対象（これに勝てなければ意味がない）
DM_LAG = 5              # Diebold-Mariano検定のNewey-Westラグ
# 事前固定の合格基準：MAIN_MODELのQLIKEがBENCHMARKより小さい銘柄の割合
ACCEPT_WIN_RATIO = 2 / 3

# ---- 答え合わせ（archive.py） -----------------------------------------------
# forecast.py を実行するたびに予報が results/archive/forecasts.csv に貯まる（実予報）。
# まだ貯まっていない分は、過去データだけで当時の予報を作り直して補う（再現）。
BACKFILL_DAYS = 250     # 再現する営業日数（0にすると再現しない）
REALIZED_WINDOW = 21    # グラフの「実際の荒れ具合」に使う前後の日数（中心化RMS）

# ---- 自己相関（acf.py） -----------------------------------------------------
ACF_MAX_LAG = 60
