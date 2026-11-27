// 外部ライブラリなしの簡易SVGチャート（全ページ共通）
const Chart = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const COLORS = ["#1f6fb2", "#e07b39", "#2f8f5b", "#8e5bb5", "#c2416b"];

  // 棒（bars）＋折れ線（lines）。labels は x 軸ラベル（日付など）
  function barLine(container, { labels, bars, barName, lines = [], yLabel = "", height = 260 }) {
    const W = Math.max(container.clientWidth || 700, 320), H = height;
    const m = { l: 46, r: 12, t: 26, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b, n = labels.length;
    const all = [...(bars || []), ...lines.flatMap(s => s.values)].filter(v => v != null);
    const ymax = Math.max(...all, 1e-9) * 1.08;
    const x = i => m.l + (i + 0.5) * iw / n, y = v => m.t + ih - v / ymax * ih;
    const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });

    for (let k = 0; k <= 4; k++) {
      const v = ymax * k / 4, yy = y(v);
      svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, stroke: "#e3e9ef" }));
      svg.appendChild(el("text", { x: m.l - 6, y: yy + 4, "text-anchor": "end", "font-size": 11, fill: "#5c6b7a" }, v.toFixed(2)));
    }
    svg.appendChild(el("text", { x: 4, y: 14, "font-size": 11, fill: "#5c6b7a" }, yLabel));
    const step = Math.ceil(n / 6);
    labels.forEach((lb, i) => {
      if (i % step === 0) svg.appendChild(el("text", { x: x(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "#5c6b7a" }, lb));
    });
    if (bars) {
      const bw = Math.max(iw / n * 0.7, 1);
      bars.forEach((v, i) => {
        if (v == null) return;
        svg.appendChild(el("rect", { x: x(i) - bw / 2, y: y(v), width: bw, height: m.t + ih - y(v), fill: "#b9cde0" }));
      });
    }
    lines.forEach((s, j) => {
      let d = "";
      s.values.forEach((v, i) => { if (v != null) d += (d && s.values[i - 1] != null ? "L" : "M") + x(i) + "," + y(v); });
      const attrs = { d, fill: "none", stroke: s.color || COLORS[j % COLORS.length], "stroke-width": s.width || 2 };
      if (s.dash) attrs["stroke-dasharray"] = "5 4";
      svg.appendChild(el("path", attrs));
    });
    // 凡例
    let lx = m.l;
    const legend = [...(bars ? [{ name: barName, color: "#b9cde0" }] : []),
                    ...lines.map((s, j) => ({ name: s.name, color: s.color || COLORS[j % COLORS.length] }))];
    legend.forEach(it => {
      svg.appendChild(el("rect", { x: lx, y: 6, width: 12, height: 10, fill: it.color }));
      svg.appendChild(el("text", { x: lx + 16, y: 15, "font-size": 12, fill: "#1d2a38" }, it.name));
      lx += 24 + it.name.length * 12;
    });
    container.innerHTML = "";
    container.appendChild(svg);
  }

  // 自己相関の棒グラフ（±band の有意線つき）
  function acfBars(container, { values, band, title, color = "#1f6fb2", height = 190 }) {
    const W = Math.max(container.clientWidth || 340, 280), H = height;
    const m = { l: 40, r: 8, t: 22, b: 22 }, iw = W - m.l - m.r, ih = H - m.t - m.b, n = values.length;
    const lim = Math.max(0.3, ...values.map(Math.abs)) * 1.1;
    const x = i => m.l + (i + 0.5) * iw / n, y = v => m.t + ih / 2 - v / lim * ih / 2;
    const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
    svg.appendChild(el("text", { x: m.l, y: 14, "font-size": 13, fill: "#1d2a38", "font-weight": "bold" }, title));
    [lim, 0, -lim].forEach(v => svg.appendChild(el("text", { x: m.l - 4, y: y(v) + 4, "text-anchor": "end", "font-size": 10, fill: "#5c6b7a" }, v.toFixed(2))));
    svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), stroke: "#999" }));
    [band, -band].forEach(b => svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(b), y2: y(b), stroke: "#d23c3c", "stroke-dasharray": "4 3" })));
    const bw = Math.max(iw / n * 0.6, 1);
    values.forEach((v, i) => {
      svg.appendChild(el("rect", { x: x(i) - bw / 2, y: Math.min(y(0), y(v)), width: bw, height: Math.abs(y(v) - y(0)), fill: color }));
    });
    [1, Math.floor(n / 2), n].forEach(k => svg.appendChild(el("text", { x: x(k - 1), y: H - 6, "text-anchor": "middle", "font-size": 10, fill: "#5c6b7a" }, k)));
    container.innerHTML = "";
    container.appendChild(svg);
  }

  // 銘柄切り替えタブ（共通）
  function tabs(container, items, onSelect) {
    container.innerHTML = "";
    items.forEach((it, i) => {
      const b = document.createElement("button");
      b.textContent = it.name;
      b.onclick = () => {
        [...container.children].forEach(c => c.classList.remove("active"));
        b.classList.add("active");
        onSelect(it);
      };
      container.appendChild(b);
      if (i === 0) b.classList.add("active");
    });
    if (items.length) onSelect(items[0]);
    // 画面の回転・幅の変化でグラフを描き直す
    let timer, lastW = window.innerWidth;
    window.addEventListener("resize", () => {
      if (Math.abs(window.innerWidth - lastW) < 40) return;
      lastW = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const i = [...container.children].findIndex(c => c.classList.contains("active"));
        if (i >= 0) onSelect(items[i]);
      }, 250);
    });
  }

  return { barLine, acfBars, tabs, COLORS };
})();
