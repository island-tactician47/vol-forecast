// 方向の見立てページ：data/trend.js（window.TREND）を表示する
(() => {
  const T = window.TREND;
  const fmt = (v, d = 1) => (v == null ? "-" : Number(v).toLocaleString("ja-JP", { maximumFractionDigits: d, minimumFractionDigits: d }));
  if (!T || !T.items || !T.items.length) return;
  document.getElementById("meta").textContent =
    `作成 ${T.generated_at} ／ k営業日後の終値が今日より上になる確率 ／ 平年の上昇率から ±${Math.round(T.band * 100)}ポイント以上で「気味」`;

  function render(it) {
    const tr = it.trend;
    const c = document.getElementById("content");
    if (!tr) {
      c.innerHTML = `<div class="card empty">${it.name}の見立てを作れませんでした。</div>`;
      return;
    }
    const last = tr.days[tr.days.length - 1];
    const days = tr.days.map(d => `
      <div class="day">
        <div class="date">${d.date}（${d.weekday}）</div>
        <div class="row">${d.k}営業日後までに</div>
        <div class="icon trend ${d.cls}">${d.arrow}</div>
        <div class="label trend ${d.cls}">${d.label}</div>
        <div class="row">終値が今日より上になる確率</div>
        <div class="vol">${fmt(d.p_up * 100, 0)}%</div>
        <div class="row">平年 ${fmt(d.base * 100, 0)}%（差 ${d.p_up - d.base >= 0 ? "+" : ""}${fmt((d.p_up - d.base) * 100, 1)}pt）</div>
      </div>`).join("");
    const ev = tr.eval.map(e => `<tr><td>${e.k}日先</td><td>${e.n}</td><td>${fmt(e.acc, 1)}%</td><td>${fmt(e.acc_base, 1)}%</td>
      <td>${fmt(e.up_rate, 1)}%</td><td>${fmt(e.t, 2)}</td>
      <td>${e.n_conf}件${e.acc_conf == null ? "" : `（的中 ${fmt(e.acc_conf, 0)}%）`}</td></tr>`).join("");
    const verdict = tr.grade === "△"
      ? "ほぼ当たらない（平年の上昇率だけで答える予想と区別できない）"
      : "1日先・5日先とも、平年の上昇率だけで答える予想より有意に良い";
    c.innerHTML = `
      <div class="card">
        <div class="headline">
          <div class="big trend ${last.cls}">${last.arrow}</div>
          <div>
            <h2>${it.name}　${T.horizon}営業日後までの見立て：<span class="trend ${last.cls}">${last.label}</span></h2>
            <div class="sub">${it.last_date} 終値 ${fmt(it.last_close, 2)}</div>
            <div class="sub">${T.horizon}営業日後に上がる確率 <b>${fmt(last.p_up * 100, 0)}%</b>（平年 ${fmt(last.base * 100, 0)}%）</div>
            <div class="conf">当たり具合 <span class="grade">${tr.grade}</span> ${verdict}</div>
          </div>
        </div>
      </div>
      <div class="card"><h3 style="margin-top:0">日ごとの見立て（今日の終値から数えた累積）</h3><div class="week">${days}</div></div>
      <div class="card"><h3 style="margin-top:0">当たり具合（直近3年の検証）</h3>
        <table><tr><th>何日先</th><th>件数</th><th>的中率</th><th>平年の多数派</th><th>実際の上昇率</th><th>平年より良いか（t）</th><th>「気味」と言った日</th></tr>${ev}</table>
        <p class="note">的中率が「平年の多数派」とほぼ同じなら、「上」と答え続けるのと変わりません。「気味」と言った日は件数が少なく、的中率は偶然でばらつきます。</p>
      </div>`;
  }

  Chart.tabs(document.getElementById("tabs"), T.items, render);
})();
