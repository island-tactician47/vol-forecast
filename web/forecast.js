// 週間予報ページ：data/forecast.js（window.FORECAST）を表示する
(() => {
  const F = window.FORECAST;
  const fmt = (v, d = 1) => (v == null ? "-" : Number(v).toLocaleString("ja-JP", { maximumFractionDigits: d, minimumFractionDigits: d }));
  if (!F || !F.items || !F.items.length) return;
  document.getElementById("meta").textContent =
    `作成 ${F.generated_at} ／ モデル ${[...new Set(F.items.map(i => i.model))].join("・")} ／ 比較期間 過去${F.lookback_years}年 ／ 大荒れ＝普段の1日の標準偏差の${F.big_move_mult}倍超（銘柄ごと）`;
  const TR = (window.TRACK && window.TRACK.items) || {};

  function render(it) {
    const t = it.today, d1 = it.days[0];
    const tk = (TR[it.key] || {});
    const grade = k => (tk[k] ? `<span class="grade" title="直近${tk[k].n}日の${k}日先：予想レンジ的中${fmt(tk[k].range_hit, 0)}%（理想68%）／大外れ${fmt(tk[k].exceed, 1)}%（理想5%）">${tk[k].grade}</span>` : "");
    const warns = (it.warnings || []).map(w => `<div class="warnbox">⚠ ${w}</div>`).join("");
    const conf = tk["1"] ? `<div class="conf">信頼度 ${grade(1)}　直近${tk["1"].n}日の1日先：予想レンジ的中 <b>${fmt(tk["1"].range_hit, 0)}%</b>（理想68%）・大外れ <b>${fmt(tk["1"].exceed, 1)}%</b>（理想5%）</div>` : "";
    const tiers = d1.prob_tiers ? `<details><summary>大荒れの基準と確率（段階別）</summary>
        <table><tr><th>基準（普段の1日の標準偏差の何倍か）</th>${it.days.map(d => `<th>${d.date}</th>`).join("")}<th>平年</th></tr>
        ${d1.prob_tiers.map((tr, j) => `<tr><td>${tr.mult}倍（±${fmt(tr.pct, 2)}%超）</td>${it.days.map(d => `<td>${fmt(d.prob_tiers[j].prob, 0)}%</td>`).join("")}<td>${fmt(tr.clim, 0)}%</td></tr>`).join("")}</table>
        <p class="note">「平年」は過去${F.lookback_years}年に実際にその動きが起きた日の割合です。予報がこれより大きいほど、荒れやすいと見ています。</p></details>` : "";
    const alert = it.alert ? `<span class="badge ${it.alert}">${it.name} ボラ${it.alert}</span>` : "";
    const days = it.days.map(d => `
      <div class="day">
        <div class="date">${d.date}（${d.weekday}）</div>
        <div class="icon">${d.weather.icon}</div>
        <div class="label">${d.weather.label}</div>
        <div class="row">その日の値動き</div>
        <div class="vol">±${fmt(d.move68)}%</div>
        <div class="row">3回に2回はこの幅に収まる</div>
        <div class="meter"><div style="width:${d.percentile}%"></div></div>
        <div class="row">過去の ${fmt(d.percentile, 0)}%点</div>
        <div class="rain">☔ ±${fmt(d.big_pct, 1)}%超の確率 <b>${fmt(d.prob_big, 0)}%</b></div>
        <div class="row">平年 ${fmt(d.prob_big_clim, 0)}%</div>
        ${grade(d.k) ? `<div class="conf">信頼度 ${grade(d.k)}</div>` : ""}
        <div class="row">終値の予想範囲<br>${fmt(d.range_low, 0)} 〜 ${fmt(d.range_high, 0)}</div>
      </div>`).join("");
    const cmp = it.comparison.map(c => `<tr><td>${c.model}${c.model === it.model ? "（主）" : ""}</td>
      <td>±${fmt(c.move68_day1, 2)}%</td><td>${fmt(c.vol_ann_day1)}%</td></tr>`).join("");
    const p = it.params;
    const params = p && p.beta_d != null ? `<p class="note">HAR-RV（翌日の係数）：日 β=${fmt(p.beta_d, 3)}　週 β=${fmt(p.beta_w, 3)}　月 β=${fmt(p.beta_m, 3)}
      ${p.beta_x != null ? `<br>前夜の先行市場（${it.exog}）の変動 β=${fmt(p.beta_x, 3)}　その下落分 β=${fmt(p.beta_xn, 3)}` : ""}
      ${p.scale != null ? `<br>終値ベースへの補正 scale=${fmt(p.scale, 2)}（直近250日で測定）` : ""}</p>`
      : p ? `<p class="note">GJR-GARCH：α=${fmt(p.alpha, 3)}　γ（下落の上乗せ）=${fmt(p.gamma, 3)}　β=${fmt(p.beta, 3)}
      持続性=${fmt(p.persistence, 4)}　半減期=${fmt(p.half_life_days, 0)}営業日　長期平均ボラ=${fmt(p.long_run_vol_ann)}%
      ${p.delta != null ? `<br>前夜の先行市場（${it.exog}）の効き：δ=${fmt(p.delta, 3)}　下落時の上乗せ δn=${fmt(p.delta_neg, 3)}` : ""}</p>` : "";

    document.getElementById("content").innerHTML = `
      <div class="card">
        ${warns}${alert}
        <div class="headline">
          <div class="big">${t.weather.icon}</div>
          <div>
            <h2>${it.name}　いまの空模様：${t.weather.label}（${t.weather.desc}）</h2>
            <div class="sub">${it.last_date} 終値 ${fmt(it.last_close, 2)}（前日比 ${it.last_return > 0 ? "+" : ""}${fmt(it.last_return, 2)}%）</div>
            <div class="sub">次の営業日は ${d1.weather.icon} ${d1.weather.label}の見込み（±${fmt(d1.move68)}%、終値 ${fmt(d1.range_low, 0)}〜${fmt(d1.range_high, 0)}）</div>
            ${conf}
          </div>
          <div><div class="sub">いまの1日の値動き</div><div class="vol">±${fmt(t.move68)}%</div><div class="sub">荒れ具合は過去の${fmt(t.percentile, 0)}%点</div></div>
        </div>
      </div>
      <div class="card"><h3 style="margin-top:0">週間予報（${F.horizon}営業日）</h3><div class="week">${days}</div>
        ${tiers}
        <p class="note">日付は、その市場の営業日（土日と祝日を除く）です。臨時の休場は考慮していません。</p></div>
      <div class="card">
        <h3 style="margin-top:0">チャート</h3>
        <div class="periods" id="periods"></div>
        <div id="price"></div>
        <h3>荒れ具合の推移（1日あたり%）</h3>
        <div id="hist"></div>
        <p class="note">予想ボラ（オレンジ）は緑の点線（後から見た実際の荒れ具合）と比べてください。
        1日ごとの|変動|（棒）は、予想が正しくても大きくばらつきます（正規分布なら平均は約0.8σ、2σ超えも約5%）。
        グラフをタップ・なぞると、その日の値が出ます。長い期間はまとめて平均しています。</p></div>
      <div class="card"><details><summary>モデル比較・パラメータ</summary>
        <table><tr><th>モデル</th><th>次の営業日の値動き</th><th>（参考）年率換算</th></tr>${cmp}</table>${params}
        <p class="note">年率換算は「この荒れ具合が1年続いたら」という仮の数字で、プロの比較用の単位です。</p>
        <p class="note">データ ${it.n_days} 日分で推定。</p></details></div>`;

    PriceChart.periodButtons(document.getElementById("periods"), period, days => { period = days; drawCharts(it); });
    drawCharts(it);
  }

  let period = 126;  // 既定は6か月（銘柄を切り替えても保つ）

  function drawCharts(it) {
    const h = it.history, n = h.dates.length;
    const start = period == null ? 0 : Math.max(0, n - period);
    const span = n - start;
    const cone = it.days.map(d => ({ date: d.date_iso, low: d.range_low, high: d.range_high }));
    PriceChart.draw(document.getElementById("price"), { h, start, cone, lastClose: it.last_close });

    const v = PriceChart.volSeries(h, start);
    const avg = v.k > 1 ? `（${v.k}日平均）` : "";
    Chart.barLine(document.getElementById("hist"), {
      labels: v.dates.map(d => Chart.dateLabel(d, span)), bars: v.abs, barName: `実際の|変動|${avg}`,
      lines: [
        { name: `予想ボラ σ（${it.model}）`, values: v.sigma, color: "#e07b39" },
        { name: `実際の荒れ具合（前後${F.realized_window}日）`, values: v.realized, color: "#2f8f5b", dash: true },
      ], yLabel: "%",
      tip: i => [v.dates[i] + (v.k > 1 ? `まで${v.k}日` : ""),
                 `実際の|変動| ${fmt(v.abs[i], 2)}%`, `予想σ ${fmt(v.sigma[i], 2)}%`,
                 v.realized[i] != null ? `実際の荒れ具合 ${fmt(v.realized[i], 2)}%` : null],
    });
  }

  Chart.tabs(document.getElementById("tabs"), F.items, render);
})();
