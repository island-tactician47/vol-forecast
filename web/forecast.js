// 週間予報ページ：data/forecast.js（window.FORECAST）を表示する
(() => {
  const F = window.FORECAST;
  const fmt = (v, d = 1) => (v == null ? "-" : Number(v).toLocaleString("ja-JP", { maximumFractionDigits: d, minimumFractionDigits: d }));
  if (!F || !F.items || !F.items.length) return;
  document.getElementById("meta").textContent =
    `作成 ${F.generated_at} ／ モデル ${F.main_model} ／ 比較期間 過去${F.lookback_years}年 ／ 大荒れ＝1日で±${F.big_move_pct}%超`;

  function render(it) {
    const t = it.today, d1 = it.days[0];
    const alert = it.alert ? `<span class="badge ${it.alert}">${it.name} ボラ${it.alert}</span>` : "";
    const days = it.days.map(d => `
      <div class="day">
        <div class="date">${d.date}（${d.weekday}）</div>
        <div class="icon">${d.weather.icon}</div>
        <div class="label">${d.weather.label}</div>
        <div class="vol">${fmt(d.vol_ann)}%</div>
        <div class="row">年率換算 ／ 1日 ±${fmt(d.sigma_daily, 2)}%</div>
        <div class="meter"><div style="width:${d.percentile}%"></div></div>
        <div class="row">過去の ${fmt(d.percentile, 0)}%点</div>
        <div class="rain">☔ 大荒れ確率 <b>${fmt(d.prob_big, 0)}%</b></div>
        <div class="row">予想レンジ（68%）<br>${fmt(d.range_low, 0)} 〜 ${fmt(d.range_high, 0)}</div>
      </div>`).join("");
    const cmp = it.comparison.map(c => `<tr><td>${c.model}${c.model === it.model ? "（主）" : ""}</td>
      <td>${fmt(c.vol_ann_day1)}%</td><td>${fmt(c.vol_ann_avg)}%</td></tr>`).join("");
    const p = it.params;
    const params = p && p.beta_d != null ? `<p class="note">HAR-RV（翌日の係数）：日 β=${fmt(p.beta_d, 3)}　週 β=${fmt(p.beta_w, 3)}　月 β=${fmt(p.beta_m, 3)}
      ${p.beta_x != null ? `<br>前夜の先行市場（${it.exog}）の変動 β=${fmt(p.beta_x, 3)}　その下落分 β=${fmt(p.beta_xn, 3)}` : ""}</p>`
      : p ? `<p class="note">GJR-GARCH：α=${fmt(p.alpha, 3)}　γ（下落の上乗せ）=${fmt(p.gamma, 3)}　β=${fmt(p.beta, 3)}
      持続性=${fmt(p.persistence, 4)}　半減期=${fmt(p.half_life_days, 0)}営業日　長期平均ボラ=${fmt(p.long_run_vol_ann)}%
      ${p.delta != null ? `<br>前夜の先行市場（${it.exog}）の効き：δ=${fmt(p.delta, 3)}　下落時の上乗せ δn=${fmt(p.delta_neg, 3)}` : ""}</p>` : "";

    document.getElementById("content").innerHTML = `
      <div class="card">
        ${alert}
        <div class="headline">
          <div class="big">${t.weather.icon}</div>
          <div>
            <h2>${it.name}　いまの空模様：${t.weather.label}（${t.weather.desc}）</h2>
            <div class="sub">${it.last_date} 終値 ${fmt(it.last_close, 2)}（前日比 ${it.last_return > 0 ? "+" : ""}${fmt(it.last_return, 2)}%）</div>
            <div class="sub">明日は ${d1.weather.icon} ${d1.weather.label}の見込み</div>
          </div>
          <div><div class="sub">現在のボラ（年率）</div><div class="vol">${fmt(t.vol_ann)}%</div><div class="sub">過去の${fmt(t.percentile, 0)}%点</div></div>
        </div>
      </div>
      <div class="card"><h3 style="margin-top:0">週間予報（${F.horizon}営業日）</h3><div class="week">${days}</div>
        <p class="note">日付は土日を除いた営業日で、祝日は考慮していません。</p></div>
      <div class="card"><h3 style="margin-top:0">これまでの値動きと予想ボラ（1日あたり%）</h3><div id="hist"></div>
        <p class="note">予想ボラ（オレンジ）は緑の点線（後から見た実際の荒れ具合）と比べてください。
        1日ごとの|変動|（棒）は、予想が正しくても大きくばらつきます（正規分布なら平均は約0.8σ、2σ超えも約5%）。</p></div>
      <div class="card"><details><summary>モデル比較・パラメータ</summary>
        <table><tr><th>モデル</th><th>明日の予想ボラ（年率）</th><th>期間平均</th></tr>${cmp}</table>${params}
        <p class="note">データ ${it.n_days} 日分で推定。</p></details></div>`;

    const h = it.history;
    Chart.barLine(document.getElementById("hist"), {
      labels: h.dates.map(s => s.slice(5)), bars: h.abs_ret, barName: "実際の|変動|",
      lines: [
        { name: `予想ボラ σ（${it.model}）`, values: h.sigma, color: "#e07b39" },
        { name: `実際の荒れ具合（前後${F.realized_window}日）`, values: h.realized, color: "#2f8f5b", dash: true },
      ], yLabel: "%",
    });
  }

  Chart.tabs(document.getElementById("tabs"), F.items, render);
})();
