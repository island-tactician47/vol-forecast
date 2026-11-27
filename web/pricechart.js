// 株価チャート（ローソク足 / 終値ライン ＋ 先の予想範囲）と、期間切り替えの共通処理
const PriceChart = (() => {
  const { el, attachTip, dateLabel } = Chart;

  // 表示期間（営業日数）。null は全期間
  const PERIODS = [
    ["1か月", 21], ["3か月", 63], ["6か月", 126], ["1年", 252],
    ["3年", 756], ["5年", 1260], ["10年", 2520], ["全期間", null],
  ];

  // 期間ボタンを作る。選んだ日数を onChange(days) に渡す
  function periodButtons(container, initial, onChange) {
    container.innerHTML = "";
    PERIODS.forEach(([label, days]) => {
      const b = document.createElement("button");
      b.textContent = label;
      if (days === initial) b.classList.add("active");
      b.onclick = () => {
        [...container.children].forEach(c => c.classList.remove("active"));
        b.classList.add("active");
        onChange(days);
      };
      container.appendChild(b);
    });
  }

  // 長い期間は k 日ずつまとめて点数を減らす（スマホでも軽く、見やすく）
  function bucketSize(n, maxPoints = 260) {
    return Math.max(1, Math.ceil(n / maxPoints));
  }

  const fmtPrice = v => (v == null ? "-" : v.toLocaleString("ja-JP", { maximumFractionDigits: v >= 100 ? 0 : 2 }));

  // h: history, start: 表示開始位置, cone: 予想範囲 [{date, low, high}]
  function draw(container, { h, start, cone = [], lastClose, height = 280 }) {
    const W = Math.max(container.clientWidth || 700, 320), H = height;
    const m = { l: 56, r: 10, t: 26, b: 28 };
    const span = h.dates.length - start;
    const candles = span <= 130 && start >= h.candle_from && h.high;
    const k = candles ? 1 : bucketSize(span);
    if (k > 1) cone = [];  // まとめて表示する長い期間では予想範囲は省く（5日分が誇張されるため）

    // 表示する点（k日まとめるときは期間の終値・高値・安値）
    const pts = [];
    for (let i = start; i < h.dates.length; i += k) {
      const j = Math.min(i + k, h.dates.length) - 1;
      const ci = idx => idx - h.candle_from;
      const p = { date: h.dates[j], close: h.close[j] };
      if (candles) {
        p.open = h.open[ci(i)]; p.high = h.high[ci(i)]; p.low = h.low[ci(i)];
      }
      pts.push(p);
    }
    const nPast = pts.length, nAll = nPast + cone.length;
    const vals = pts.flatMap(p => [p.close, p.high, p.low]).concat(cone.flatMap(c => [c.low, c.high])).filter(v => v != null);
    let ymin = Math.min(...vals), ymax = Math.max(...vals);
    const pad = (ymax - ymin) * 0.06 || ymax * 0.01;
    ymin -= pad; ymax += pad;
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const x = i => m.l + (i + 0.5) * iw / nAll, y = v => m.t + ih - (v - ymin) / (ymax - ymin) * ih;
    const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });

    for (let g = 0; g <= 4; g++) {
      const v = ymin + (ymax - ymin) * g / 4;
      svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "#e3e9ef" }));
      svg.appendChild(el("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "#5c6b7a" }, fmtPrice(v)));
    }
    const labelEvery = Math.ceil(nAll / 5);
    pts.forEach((p, i) => {
      if (i % labelEvery === 0) svg.appendChild(el("text", { x: x(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "#5c6b7a" }, dateLabel(p.date, span)));
    });

    // 予想範囲（先の日付の帯）
    if (cone.length) {
      const c0 = { x: x(nPast - 1), y: y(lastClose) };
      let d = `M${c0.x},${c0.y}`;
      cone.forEach((c, i) => { d += `L${x(nPast + i)},${y(c.high)}`; });
      for (let i = cone.length - 1; i >= 0; i--) d += `L${x(nPast + i)},${y(cone[i].low)}`;
      svg.appendChild(el("path", { d: d + "Z", fill: "rgba(224,123,57,.18)", stroke: "#e07b39", "stroke-width": 1, "stroke-dasharray": "4 3" }));
      svg.appendChild(el("text", { x: x(nPast + cone.length - 1), y: y(cone[cone.length - 1].high) - 6, "text-anchor": "end", "font-size": 11, fill: "#c0602a" }, "予想範囲"));
    }

    if (candles) {
      const bw = Math.max(iw / nAll * 0.65, 1.5);
      pts.forEach((p, i) => {
        if (p.open == null || p.high == null) return;
        const up = p.close >= p.open, col = up ? "#d23c3c" : "#1f6fb2";  // 日本式：陽線=赤、陰線=青
        svg.appendChild(el("line", { x1: x(i), x2: x(i), y1: y(p.high), y2: y(p.low), stroke: col }));
        const top = y(Math.max(p.open, p.close)), bot = y(Math.min(p.open, p.close));
        svg.appendChild(el("rect", { x: x(i) - bw / 2, y: top, width: bw, height: Math.max(bot - top, 1), fill: col }));
      });
    } else {
      let d = "";
      pts.forEach((p, i) => { if (p.close != null) d += (d ? "L" : "M") + x(i) + "," + y(p.close); });
      svg.appendChild(el("path", { d, fill: "none", stroke: "#1f6fb2", "stroke-width": 1.8 }));
    }
    svg.appendChild(el("text", { x: m.l, y: 15, "font-size": 12, fill: "#1d2a38" },
      candles ? "ローソク足（赤=上昇・青=下落）" : (k > 1 ? `終値（${k}営業日ごと）` : "終値")));

    attachTip(svg, {
      m, W, H, n: nAll, x, tip: i => {
        if (i < nPast) {
          const p = pts[i];
          return [p.date, `終値 ${fmtPrice(p.close)}`,
                  p.high != null ? `高 ${fmtPrice(p.high)} 安 ${fmtPrice(p.low)}` : null];
        }
        const c = cone[i - nPast];
        return [`${c.date}（予想）`, `${fmtPrice(c.low)}〜${fmtPrice(c.high)}`];
      },
    });
    container.innerHTML = "";
    container.appendChild(svg);
  }

  // ボラのグラフ用：期間を切り出し、長い期間は k 日平均にまとめる
  function volSeries(h, start) {
    const span = h.dates.length - start, k = bucketSize(span);
    const out = { k, dates: [], abs: [], sigma: [], realized: [] };
    const avg = a => { const v = a.filter(x => x != null); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
    for (let i = start; i < h.dates.length; i += k) {
      const j = Math.min(i + k, h.dates.length);
      out.dates.push(h.dates[j - 1]);
      out.abs.push(avg(h.abs_ret.slice(i, j)));
      out.sigma.push(avg(h.sigma.slice(i, j)));
      out.realized.push(avg(h.realized.slice(i, j)));
    }
    return out;
  }

  return { PERIODS, periodButtons, draw, volSeries, fmtPrice };
})();
