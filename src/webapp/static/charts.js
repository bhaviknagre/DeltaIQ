// Hand-rolled, dependency-free SVG chart rendering (no CDN, no chart
// library) — reads chart data from data-* attributes on elements with
// class="chart" and renders bar / donut / gauge / trend charts into them.
(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function renderBar(container, data, colors) {
    const keys = Object.keys(data);
    const max = Math.max(1, ...keys.map((k) => data[k]));
    const w = 320, h = 140, barW = 60, gap = 30, baseY = 110;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}` });
    keys.forEach((key, i) => {
      const x = 20 + i * (barW + gap);
      const value = data[key];
      const barH = (value / max) * 80;
      const color = (colors && colors[key]) || "#5b8def";
      svg.appendChild(el("rect", { x, y: baseY - barH, width: barW, height: barH, rx: 4, fill: color }));
      const label = el("text", { x: x + barW / 2, y: baseY + 16, "text-anchor": "middle", fill: "currentColor", "font-size": "11" });
      label.textContent = key;
      svg.appendChild(label);
      const val = el("text", { x: x + barW / 2, y: baseY - barH - 6, "text-anchor": "middle", fill: "currentColor", "font-size": "13", "font-weight": "700" });
      val.textContent = value;
      svg.appendChild(val);
    });
    container.appendChild(svg);
  }

  function renderDonut(container, data, colors) {
    const keys = Object.keys(data);
    const total = keys.reduce((s, k) => s + data[k], 0) || 1;
    const r = 46, cx = 60, cy = 60, stroke = 20;
    const circumference = 2 * Math.PI * r;
    const svg = el("svg", { viewBox: "0 0 220 120" });
    let offset = 0;
    keys.forEach((key) => {
      const frac = data[key] / total;
      const len = frac * circumference;
      const color = (colors && colors[key]) || "#5b8def";
      const circle = el("circle", {
        cx, cy, r, fill: "none", stroke: color, "stroke-width": stroke,
        "stroke-dasharray": `${len} ${circumference - len}`,
        "stroke-dashoffset": -offset, transform: `rotate(-90 ${cx} ${cy})`,
      });
      svg.appendChild(circle);
      offset += len;
    });
    const centerText = el("text", { x: cx, y: cy + 5, "text-anchor": "middle", "font-size": "16", "font-weight": "700", fill: "currentColor" });
    centerText.textContent = total;
    svg.appendChild(centerText);

    let ly = 20;
    keys.forEach((key) => {
      const color = (colors && colors[key]) || "#5b8def";
      svg.appendChild(el("rect", { x: 140, y: ly - 9, width: 10, height: 10, rx: 2, fill: color }));
      const t = el("text", { x: 156, y: ly, "font-size": "11", fill: "currentColor" });
      t.textContent = `${key}: ${data[key]}`;
      svg.appendChild(t);
      ly += 18;
    });
    container.appendChild(svg);
  }

  function gaugeColor(value) {
    if (value >= 0.9) return "#22c55e";
    if (value >= 0.75) return "#f59e0b";
    return "#ef4444";
  }

  function renderGauge(container, value, label) {
    const w = 220, h = 130, cx = 110, cy = 110, r = 90;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}` });
    const startAngle = Math.PI, endAngle = 0;
    const describeArc = (frac) => {
      const angle = startAngle - frac * Math.PI;
      const x = cx + r * Math.cos(angle);
      const y = cy - r * Math.sin(angle);
      return { x, y };
    };
    const bgStart = describeArc(0), bgEnd = describeArc(1);
    svg.appendChild(el("path", {
      d: `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`,
      fill: "none", stroke: "var(--border, #e5e7eb)", "stroke-width": 16, "stroke-linecap": "round",
    }));
    const frac = Math.max(0, Math.min(1, value));
    const valEnd = describeArc(frac);
    svg.appendChild(el("path", {
      d: `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${valEnd.x} ${valEnd.y}`,
      fill: "none", stroke: gaugeColor(value), "stroke-width": 16, "stroke-linecap": "round",
    }));
    const valText = el("text", { x: cx, y: cy - 6, "text-anchor": "middle", "font-size": "26", "font-weight": "800", fill: "currentColor" });
    valText.textContent = value.toFixed(2);
    svg.appendChild(valText);
    const labText = el("text", { x: cx, y: cy + 16, "text-anchor": "middle", "font-size": "12", fill: "currentColor", opacity: 0.65 });
    labText.textContent = label || "";
    svg.appendChild(labText);
    container.appendChild(svg);
  }

  function renderTrend(container, history) {
    if (!history || history.length === 0) {
      container.textContent = "No history yet.";
      return;
    }
    const width = 640, height = 180, padL = 30, padB = 20, padT = 10;
    const plotH = height - padT - padB;
    const n = history.length;
    const xStep = n > 1 ? (width - padL - 20) / (n - 1) : 0;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}` });
    const yFor = (value) => padT + (1 - value) * plotH;
    const xFor = (i) => padL + i * xStep;

    [0, 0.25, 0.5, 0.75, 1].forEach((frac) => {
      const y = yFor(frac);
      svg.appendChild(el("line", { x1: padL, y1: y, x2: width - 10, y2: y, stroke: "var(--border, #e5e7eb)", "stroke-width": 1 }));
      const t = el("text", { x: 2, y: y + 4, "font-size": "9", fill: "currentColor", opacity: 0.6 });
      t.textContent = frac.toFixed(2);
      svg.appendChild(t);
    });

    const series = [
      { key: "native_f1", color: "#5b8def", label: "native F1" },
      { key: "scanned_f1", color: "#f59e0b", label: "scanned F1" },
      { key: "chat_acc", color: "#22c55e", label: "chat accuracy" },
    ];

    series.forEach((s) => {
      const points = [];
      history.forEach((run, i) => {
        if (run[s.key] == null) return;
        points.push([xFor(i), yFor(run[s.key])]);
      });
      if (points.length === 0) return;
      const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ");
      svg.appendChild(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2 }));
      points.forEach(([cx, cy]) => svg.appendChild(el("circle", { cx, cy, r: 3, fill: s.color })));
    });

    let lx = width - 150, ly = 16;
    series.forEach((s) => {
      svg.appendChild(el("rect", { x: lx, y: ly - 8, width: 9, height: 9, fill: s.color, rx: 2 }));
      const t = el("text", { x: lx + 13, y: ly, "font-size": "10", fill: "currentColor" });
      t.textContent = s.label;
      svg.appendChild(t);
      ly += 15;
    });

    container.appendChild(svg);
  }

  function init() {
    document.querySelectorAll(".chart").forEach((container) => {
      const kind = container.dataset.kind;
      try {
        if (kind === "bar") {
          renderBar(container, JSON.parse(container.dataset.chart), JSON.parse(container.dataset.colors || "{}"));
        } else if (kind === "donut") {
          renderDonut(container, JSON.parse(container.dataset.chart), JSON.parse(container.dataset.colors || "{}"));
        } else if (kind === "gauge") {
          renderGauge(container, parseFloat(container.dataset.value), container.dataset.label);
        } else if (kind === "trend") {
          renderTrend(container, JSON.parse(container.dataset.history || "[]"));
        }
      } catch (e) {
        container.textContent = "Chart error: " + e.message;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
