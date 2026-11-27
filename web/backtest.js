// 検証ページ：data/backtest.js（window.BACKTEST）を表示する
(() => {
  const B = window.BACKTEST;
  const fmt = (v, d = 4) => (v == null ? "-" : Number(v).toFixed(d));
  if (!B || !B.items || !B.items.length) return;
  document.getElementById("meta").textContent =
    `作成 ${B.generated_at} ／ 直近${B.test_years}年を検証 ／ ${B.refit_days}営業日ごとに再推定（拡大窓）`;
  document.getElementById("verdict").innerHTML =
    `<span class="badge ${B.passed ? "pass" : "fail"}">${B.passed ? "合格" : "不合格"}</span>　${B.verdict}
     <p class="note">合格基準は config.py の ACCEPT_WIN_RATIO で事前に固定。試行の履歴は results/backtest_log.csv。</p>`;

  function render(it) {
    const rows = it.rows.map((r, i) => `<tr><td>${i === 0 ? "🥇 " : ""}${r.model}${r.model === B.benchmark ? "（基準）" : ""}</td>
      <td>${fmt(r.qlike)}</td><td>${fmt(r.mse, 2)}</td><td>${fmt(r.miss95, 1)}%</td>
      <td>${r.dm_stat == null ? "-" : fmt(r.dm_stat, 2)}</td><td>${r.dm_p == null ? "-" : fmt(r.dm_p, 3)}</td></tr>`).join("");
    document.getElementById("content").innerHTML = `
      <div class="card"><h3 style="margin-top:0">${it.name}　${it.test_start} 〜 ${it.test_end}（${it.n_test}日）</h3>
        <table><tr><th>モデル</th><th>QLIKE</th><th>MSE</th><th>95%外れ率</th><th>DM統計量</th><th>p値</th></tr>${rows}</table></div>
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
