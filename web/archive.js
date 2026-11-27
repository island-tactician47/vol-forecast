// 答え合わせページ：data/archive.js（window.ARCHIVE）を表示する
(() => {
  const A = window.ARCHIVE;
  if (!A || !A.items || !A.items.length) return;
  const W = A.weather, BIG = A.big_move_pct;
  const pct = v => (v == null || isNaN(v) ? "-" : `${Math.round(v * 100)}%`);
  const mean = a => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN);
  const wx = i => (i == null ? "" : `<span class="icon">${W[i].icon}</span>${W[i].label}`);
  document.getElementById("meta").textContent =
    `作成 ${A.generated_at} ／ モデル ${A.main_model} ／ 大荒れ＝1日で±${BIG}%超`;

  const kSel = document.getElementById("kSel"), src = document.getElementById("src");
  for (let k = 1; k <= A.horizon; k++) kSel.add(new Option(`${k}営業日先${k === 1 ? "（翌日）" : ""}`, k));
  document.getElementById("controls").hidden = false;
  let current = A.items[0], shown = 30;
  kSel.onchange = src.onchange = () => { shown = 30; render(current); };

  function scoreCard(title, value, sub, ok) {
    return `<div class="score ${ok === true ? "good" : ok === false ? "bad" : ""}">
      <div class="t">${title}</div><div class="v">${value}</div><div class="s">${sub}</div></div>`;
  }

  function render(it) {
    current = it;
    const k = +kSel.value;
    const rows = it.rows.filter(x => x.k === k && (src.value === "all" || x.s === +src.value));
    const done = rows.filter(x => x.ar != null);
    const c = document.getElementById("content");
    if (!done.length) {
      c.innerHTML = `<div class="card empty">この条件で答えが出た予報はまだありません（答え待ち ${rows.length} 件）。</div>`;
      if (rows.length) c.innerHTML += table(rows);
      return;
    }

    // ---- 成績 ----
    const within1 = mean(done.map(x => Math.abs(x.pf - x.aw) <= 1 ? 1 : 0));
    const exact = mean(done.map(x => (x.pf === x.aw ? 1 : 0)));
    const bench = mean(done.map(x => Math.abs(2 - x.aw) <= 1 ? 1 : 0)); // 毎日「くもり」
    const inRange = mean(done.map(x => (x.lo <= x.cl && x.cl <= x.hi ? 1 : 0)));
    const exceed = mean(done.map(x => (Math.abs(x.ar) > 1.96 * x.sg ? 1 : 0)));
    const y = done.map(x => (Math.abs(x.ar) > BIG ? 1 : 0));
    const brier = mean(done.map((x, i) => (x.pb / 100 - y[i]) ** 2));
    const brierClim = mean(done.map((x, i) => ((x.cb ?? 0) / 100 - y[i]) ** 2));
    const skill = 1 - brier / brierClim;

    // ---- 予報天気ごとの実際 ----
    const groups = W.map((w, i) => {
      const g = done.filter(x => x.pf === i);
      return { i, n: g.length, ar: mean(g.map(x => Math.abs(x.ar))), big: mean(g.map(x => (Math.abs(x.ar) > BIG ? 1 : 0))),
               sg: mean(g.map(x => x.sg)) };
    });
    const maxAr = Math.max(...groups.map(g => g.ar || 0), 0.01);
    const gRows = groups.map(g => `<tr><td>${wx(g.i)}</td><td>${g.n}</td>
      <td>${g.n ? g.sg.toFixed(2) + "%" : "-"}</td>
      <td>${g.n ? `<span class="bar" style="width:${g.ar / maxAr * 80}px"></span> ${g.ar.toFixed(2)}%` : "-"}</td>
      <td>${g.n ? pct(g.big) : "-"}</td></tr>`).join("");

    c.innerHTML = `
      <div class="card"><h3 style="margin-top:0">${it.name}　成績表（${k}営業日先・答えが出た ${done.length} 件）</h3>
        <div class="scores">
          ${scoreCard("予想レンジに収まった割合", pct(inRange), "理想は約68%（±1σの範囲）", Math.abs(inRange - 0.68) <= 0.08)}
          ${scoreCard("大外れ（±1.96σ超え）の割合", pct(exceed), "理想は約5%。多すぎると荒れを甘く見ている", exceed <= 0.08)}
          ${scoreCard("天気の的中（±1段階以内）", pct(within1), `ぴったり ${pct(exact)}／参考：毎日「くもり」と言うと ${pct(bench)}`, within1 > bench)}
          ${scoreCard("大荒れ予報のスキル", isFinite(skill) ? skill.toFixed(2) : "-",
             `予報の平均 ${mean(done.map(x => x.pb)).toFixed(0)}% → 実際 ${pct(mean(y))}。0より大きければ「平年並み」より役立つ`, isFinite(skill) ? skill > 0 : null)}
        </div>
        <p class="note">天気の「実際」は、その日の|変動|が過去の|変動|の何%点だったかで決めています。1日の値動きは偶然でぶれるため、天気の的中率は低めに出ます。</p>
      </div>
      <div class="card"><h3 style="margin-top:0">予報した天気ごとの、実際の値動き</h3>
        <table><tr><th>予報した天気</th><th>件数</th><th>予想σ（平均）</th><th>実際の平均|変動|</th><th>大荒れ発生率</th></tr>${gRows}</table>
        <p class="note">晴れの日ほど小さく、荒れ予報の日ほど大きくなっていれば、予報は荒れ具合の順番を当てられています。</p>
      </div>
      <div class="card"><h3 style="margin-top:0">予報と実際の推移（対象日ごと）</h3><div id="chart"></div></div>
      ${table(rows)}`;

    const cs = done.slice(-250);
    Chart.barLine(document.getElementById("chart"), {
      labels: cs.map(x => x.t.slice(2)), bars: cs.map(x => Math.abs(x.ar)), barName: "実際の|変動|",
      lines: [{ name: "予想σ", values: cs.map(x => x.sg), color: "#e07b39" },
              { name: "1.96σ（超えたら大外れ）", values: cs.map(x => 1.96 * x.sg), color: "#d23c3c", dash: true, width: 1.2 }],
      yLabel: "%", height: 280,
    });
  }

  function table(rows) {
    const list = rows.slice().reverse();
    const body = list.slice(0, shown).map(x => {
      const done = x.ar != null;
      const rangeHit = done && x.lo <= x.cl && x.cl <= x.hi;
      const big = done && Math.abs(x.ar) > BIG;
      return `<tr class="src${x.s}"><td>${x.b}</td><td>${x.t}${done ? "" : "（予定）"}</td><td>${x.s ? "再現" : "実予報"}</td>
        <td>${wx(x.pf)}</td><td>${done ? wx(x.aw) : '<span class="wait">答え待ち</span>'}</td>
        <td>±${x.sg.toFixed(2)}%</td>
        <td>${done ? (x.ar > 0 ? "+" : "") + x.ar.toFixed(2) + "%" : "-"}</td>
        <td>${done ? `<span class="${rangeHit ? "hit" : "miss"}">${rangeHit ? "○" : "×"}</span> ` : ""}${x.lo.toLocaleString()}〜${x.hi.toLocaleString()}</td>
        <td>${x.pb}%${done ? (big ? " → ⚡あり" : " → なし") : ""}</td></tr>`;
    }).join("");
    const more = list.length > shown ? `<button class="more" id="more">さらに表示（残り ${list.length - shown} 件）</button>` : "";
    setTimeout(() => {
      const b = document.getElementById("more");
      if (b) b.onclick = () => { shown += 100; render(current); };
    });
    return `<div class="card"><h3 style="margin-top:0">予報の記録（新しい順）</h3>
      <table><tr><th>基準日</th><th>対象日</th><th>出どころ</th><th>予報</th><th>実際</th><th>予想σ</th>
      <th>実際の変動</th><th>予想レンジ</th><th>大荒れ確率→実際</th></tr>${body}</table>${more}</div>`;
  }

  Chart.tabs(document.getElementById("tabs"), A.items, it => { shown = 30; render(it); });
})();
