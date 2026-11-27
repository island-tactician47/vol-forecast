// 全ページ共通：ヘッダーに更新ボタンを付ける（ホーム画面から開いたときはブラウザの更新ボタンが無いため）
(() => {
  const header = document.querySelector("header");
  if (!header) return;
  const b = document.createElement("button");
  b.className = "reload";
  b.type = "button";
  b.textContent = "↻ 更新";
  b.setAttribute("aria-label", "最新の予報を読み込む");
  b.onclick = () => {
    b.textContent = "読み込み中…";
    b.disabled = true;
    location.reload();
  };
  header.appendChild(b);
})();

// データファイルを毎回最新で読む（キャッシュされた古い予報を表示しないように）
function loadData(name) {
  document.write(`<script src="data/${name}?v=${Date.now()}"><\/script>`);
}
