# ボラ予報（ボラティリティの天気予報）

株価・指数の「値動きの大きさ（ボラティリティ）」を数営業日先まで予測し、天気予報のように表示する雛形です。
方向（上がる・下がる）は予測しません。

## 使い方
1. `launch.bat` をダブルクリック（ランチャーが開く）
2. 初回は「まとめて ①→②」→ 週間予報ページが自動で開く
3. 精度を確かめるときは「③ 予測精度の検証」→「当たり具合ページ」

必要なもの：Python 3、numpy、pandas、scipy（＋データ自動取得に yfinance）
```
pip install numpy pandas scipy yfinance
```

## ファイル構成（機能ごとに分割）
| ファイル | 役割 |
|---|---|
| `launcher.py` / `launch.bat` | ランチャー（計算ボタンとページを開くボタン） |
| `config.py` | 設定（銘柄、予報日数、天気のしきい値、合格基準など） |
| `data_io.py` | CSV読み込み・リターン計算・ページ用データ書き出し |
| `models.py` | モデル（GJR-GARCH、EWMA、過去20日、HAR-RV） |
| `data_fetch.py` | ① yfinanceで日足を取得 → `data/` |
| `forecast.py` | ② 予報 → `web/data/forecast.js` |
| `backtest.py` | ③ 検証 → `web/data/backtest.js`、試行ログ `results/backtest_log.csv` |
| `acf.py` | ④ 自己相関 → `web/data/acf.js` |
| `archive.py` | ⑤ 答え合わせ → `web/data/archive.js`（予報の記録は `results/archive/`） |
| `web/forecast.*` | 週間予報ページ |
| `web/backtest.*` | 当たり具合ページ |
| `web/archive.*` | 答え合わせページ |
| `web/acf.html` | 自己相関ページ |
| `web/chart.js`, `web/common.css` | ページ共通の部品 |

## 天気の決め方
- 主モデル（既定は HAR-RV。高値・安値が無い銘柄は GJR-GARCH）の予想ボラが、過去10年の同モデルのボラの何%点かで天気を決める
  - ☀️快晴 〜20% / 🌤️晴れ 〜40% / ⛅くもり 〜60% / 🌧️雨 〜80% / ⛈️雷雨 〜95% / 🌀台風
- 予報期間中に80%点以上で「注意報」、95%点以上で「警報」
- ☔大荒れ確率：1日の変動が±2%を超える確率。正規分布ではなく、モデルの標準化残差の実績分布から計算（裾の厚さを反映）
- 予想レンジ：約68%の確率で収まる範囲。標準化残差の実績分布の分位点から求める（正規分布より狭くはしない）
- 大外れライン：同じく実績分布の95%点。答え合わせの「大外れ率」はこれを超えた日の割合

## モデルの補足
- GJR-GARCH(1,1)：正規分布の擬似最尤。γ が「下落時にボラが上がる」非対称性
- 日経平均は前夜の米国株（S&P500）の変動とその下落分を説明変数に加える（HAR-RV のみ。`config.EXOG`）
- HAR-RV：日足しかないため、実現分散を高値・安値（Parkinson推定量）で代用。夜間の窓の分は終値ベースとの比で補正。k日先は直接推定
- 新しいモデルは `models.py` に `fit / one_step / forecast` を持つクラスを作り、`build_models()` に追加

## 検証の考え方
- 直近3年を検証期間、250営業日ごとに過去データだけで再推定（拡大窓）
- 損失：QLIKE と MSE（代理変数 r² でも順位が歪まない損失）
- 95%外れ率（理想5%）、基準モデル（EWMA）との Diebold-Mariano 検定
- 合格基準は `config.py` で事前固定し、試行のたびにログへ追記

## 答え合わせ（アーカイブ）
- ② 予報を計算するたびに、予報が `results/archive/forecasts.csv` に自動で貯まる（実予報）
- ⑤ 答え合わせで、実際の値動きと突き合わせる。実予報が少ないうちは、その日までのデータだけで作り直した「再現」予報（直近250営業日）でも成績を確認できる
- 成績：予想レンジ的中率（理想68%）、大外れ率（±1.96σ超え、理想5%）、天気の的中率（毎日「くもり」と言った場合と比較）、大荒れ予報のブライアスキル（平年値と比較）、予報天気ごとの実際の値動き
- 毎日 ①→②、ときどき ⑤ を回すと記録が育つ

## スマホで使う（GitHub Pages ＋ 毎朝の自動更新）
GitHubが毎朝（日本時間7:35ごろ、火〜土）データ取得→予報→答え合わせを実行してページを更新する。PCの電源は不要。

1. GitHubで新しいリポジトリを作る（例：`vol-forecast`。無料プランでPagesを使うには Public）
2. この「ボラ予報」フォルダの中身を丸ごとリポジトリに入れる
   - `workflow/update.yml` は、リポジトリ内の `.github/workflows/update.yml` に置く（フォルダを作って移すか、GitHubの Actions タブ →「set up a workflow yourself」で中身を貼り付けて保存）
   - git の場合：フォルダ内で `git init` → `git add .` → `git commit -m "init"` → リモートを登録して `git push`
   - ブラウザの場合：リポジトリの「Add file → Upload files」にフォルダの中身をドラッグ
3. リポジトリの Settings → Pages → Source を「GitHub Actions」にする
4. Actions タブ →「毎朝の予報更新」→「Run workflow」で初回を手動実行（検証③も初回だけ走る）
5. 数分後、`https://<ユーザー名>.github.io/<リポジトリ名>/` が開けるようになる
6. iPhone：Safariで開いて「共有 → ホーム画面に追加」　Android：Chromeのメニュー →「ホーム画面に追加」

補足
- 予報の記録（`results/archive/forecasts.csv`）は毎朝リポジトリに保存されて貯まっていく
- 検証③は試行回数を記録するので、自動では回さず「Run workflow」のときだけ実行
- PCでも並行して回すと記録が別々になるので、記録はGitHub側を正とする（PC側はコードの改造・試行用）
- コードを直したら、変更をリポジトリに push すれば翌朝から反映（すぐ見たいときは Run workflow）

## 今後の拡張候補
- t分布・歪みt分布のGARCH、EGARCH
- 日中データ（Dukascopyの1分足など）からの本物の実現ボラでHAR-RV
- VIXなど外部変数の追加、祝日カレンダー対応
