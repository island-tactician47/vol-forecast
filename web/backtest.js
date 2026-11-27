// 検証ページ：data/backtest.js（window.BACKTEST）を表示する
(() => {
  const B = window.BACKTEST;
  const fmt = (v, d = 4) => (v == null ? "-" : Number(v).toFixed(d));
  if (!B || !B.items || !B.items.length) return;
  document.getElementById("meta").textContent =
    `作成 ${B.generated_at} ／ 直近${B.test_years}年を検証 ／ ${B.refit_days}営業日ごとに再推定（拡大窓）`;
  document.getElementById("verdict").innerHTML =
    `<span class="badge ${B.passed ? "pass" : "fail"}">${B.passed ? "合格" : "不合格"}</span>　${B.verdict}
     ${B.verdict_k ? `<p class="note">参考（合否には使いません）：日数別に、${B.main_model} が ${B.benchmark} に勝った銘柄数　${B.verdict_k.map(v => `${v.k}日先 ${v.wins}/${v.n}`).join("　")}</p>` : ""}
     <p class="note">合格基準は config.py の ACCEPT_WIN_RATIO で事前に固定。試行の履歴は results/backtest_log.csv。</p>`;

  // 何日先の予報か別の QLIKE。★は基準より有意（p<0.05）に良い
  function byK(it) {
    if (!it.by_k || !it.by_k.length) return "";
    const models = it.by_k[0].rows.map(r => r.model);
    const cell = (k, m) => {
      const r = it.by_k.find(x => x.k === k).rows.find(x => x.model === m);
      if (!r) return "-";
      const star = r.dm_p != null && r.dm_p < 0.05 && r.dm_stat < 0 ? "★" : "";
      return `${fmt(r.qlike, 3)}${star}`;
    };
    const head = it.by_k.map(x => `<th>${x.k}日先</th>`).join("");
    const body = models.map(m => `<tr><td>${m}${m === B.benchmark ? "（基準）" : ""}</td>${it.by_k.map(x => `<td>${cell(x.k, m)}</td>`).join("")}</tr>`).join("");
    return `<div class="card"><h3 style="margin-top:0">何日先の予報か別の成績（QLIKE。小さいほど良い）</h3>
      <table><tr><th>モデル</th>${head}</tr>${body}</table>
      <p class="note">★は${B.benchmark}より有意（p&lt;0.05）に良いもの。k日先は「k営業日前までの情報で作った、その日1日分の分散の予測」です。</p></div>`;
  }

  function render(it) {
    const rows = it.rows.map((r, i) => `<tr><td>${i === 0 ? "🥇 " : ""}${r.model}${r.model === B.benchmark ? "（基準）" : ""}</td>
      <td>${fmt(r.qlike)}</td><td>${fmt(r.mse, 2)}</td><td>${fmt(r.miss95, 1)}%</td><td>${r.miss95_emp == null ? "-" : fmt(r.miss95_emp, 1) + "%"}</td>
      <td>${r.dm_stat == null ? "-" : fmt(r.dm_stat, 2)}</td><td>${r.dm_p == null ? "-" : fmt(r.dm_p, 3)}</td></tr>`).join("");
    document.getElementById("content").innerHTML = `
      <div class="card"><h3 style="margin-top:0">${it.name}　${it.test_start} 〜 ${it.test_end}（${it.n_test}日）</h3>
        <table><tr><th>モデル</th><th>QLIKE</th><th>MSE</th><th>95%外れ率（正規）</th><th>同（実績分布）</th><th>DM統計量</th><th>p値</th></tr>${rows}</table></div>
      ${byK(it)}
      <div class="card"><h3 style="margin-top:0">直近の予想ボラと実際の|変動|（1日あたり%）</h3><div id="chart"></div></div>`;
    const c = it.chart;
    Chart.barLine(document.getElementById("chart"), {
      labels: c.dates.map(s => s.slice(2)), bars: c.abs_ret, barName: "実際の|変動|",
      lines: [...Object.entries(c.series).map(([name, values]) => ({ name, values })),
              { name: "実際の荒れ具合", values: c.realized, color: "#555", dash: true, width: 1.5 }],
      yLabel: "%", height: 300,
    });
  }

  Chart.tabs(document.getElementById("tabs"), B.items, render);
})();
