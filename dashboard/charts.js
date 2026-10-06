/* Small SVG chart helpers. No dependencies, so the page opens from the filesystem
   and keeps working with no network. */
(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var tooltip = null;

  function el(name, attrs) {
    var node = document.createElementNS(NS, name);
    for (var key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    }
    return node;
  }

  function svgRoot(host, width, height) {
    host.textContent = "";
    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height,
      preserveAspectRatio: "xMidYMid meet",
      role: "img"
    });
    host.appendChild(svg);
    return svg;
  }

  function text(parent, x, y, value, className, anchor) {
    var node = el("text", { x: x, y: y, class: className, "text-anchor": anchor || "start" });
    node.textContent = value;
    parent.appendChild(node);
    return node;
  }

  /* Rounded only on the data end, anchored flat to the baseline. */
  function barPath(x, y, w, h, r, horizontal) {
    if (w <= 0 || h <= 0) return "";
    var radius = Math.max(0, Math.min(r, horizontal ? w : h, (horizontal ? h : w) / 2));
    if (horizontal) {
      return "M" + x + "," + y +
        "H" + (x + w - radius) + "a" + radius + "," + radius + " 0 0 1 " + radius + "," + radius +
        "V" + (y + h - radius) + "a" + radius + "," + radius + " 0 0 1 " + (-radius) + "," + radius +
        "H" + x + "Z";
    }
    return "M" + x + "," + (y + h) +
      "V" + (y + radius) + "a" + radius + "," + radius + " 0 0 1 " + radius + "," + (-radius) +
      "H" + (x + w - radius) + "a" + radius + "," + radius + " 0 0 1 " + radius + "," + radius +
      "V" + (y + h) + "Z";
  }

  /* A bar hanging below the baseline: same shape, rounded on the bottom instead. */
  function barPathDown(x, y, w, h, r) {
    if (w <= 0 || h <= 0) return "";
    var radius = Math.max(0, Math.min(r, h, w / 2));
    return "M" + x + "," + y +
      "H" + (x + w) +
      "V" + (y + h - radius) + "a" + radius + "," + radius + " 0 0 1 " + (-radius) + "," + radius +
      "H" + (x + radius) + "a" + radius + "," + radius + " 0 0 1 " + (-radius) + "," + (-radius) +
      "Z";
  }

  /* The sequential ramp runs light-to-dark in one theme and dark-to-light in the other,
     so label contrast has to come from the resolved colour, not from the value. */
  function resolveColor(value) {
    var name = /^var\((--[^)]+)\)$/.exec(value.trim());
    if (!name) return value.trim();
    return getComputedStyle(document.documentElement).getPropertyValue(name[1]).trim();
  }

  function isLight(color) {
    var hex = resolveColor(color).replace("#", "");
    if (hex.length === 3) hex = hex.replace(/./g, "$&$&");
    if (hex.length < 6) return true;
    var channels = [0, 2, 4].map(function (i) {
      var c = parseInt(hex.substr(i, 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2] > 0.3;
  }

  function ensureTooltip() {
    if (!tooltip) tooltip = document.getElementById("tooltip");
    return tooltip;
  }

  function showTip(event, html) {
    var tip = ensureTooltip();
    if (!tip) return;
    tip.innerHTML = html;
    tip.classList.add("is-visible");
    moveTip(event);
  }

  function moveTip(event) {
    var tip = ensureTooltip();
    if (!tip) return;
    var box = tip.getBoundingClientRect();
    var x = event.clientX + 14;
    var y = event.clientY + 14;
    if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - 14;
    if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }

  function hideTip() {
    var tip = ensureTooltip();
    if (tip) tip.classList.remove("is-visible");
  }

  function bindTip(node, html) {
    node.addEventListener("mouseenter", function (e) { showTip(e, html); });
    node.addEventListener("mousemove", moveTip);
    node.addEventListener("mouseleave", hideTip);
  }

  function tipRows(title, rows) {
    var html = "<strong>" + title + "</strong>";
    rows.forEach(function (row) {
      html += '<div class="t-row"><span>' + row[0] + "</span><b>" + row[1] + "</b></div>";
    });
    return html;
  }

  function niceTicks(max, count) {
    if (max <= 0) return [0];
    var raw = max / count;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; })
      .find(function (s) { return s >= raw; }) || mag * 10;
    // round the top tick UP past the peak, or the tallest mark draws outside the plot
    var steps = Math.ceil(max / step - 1e-9);
    var ticks = [];
    for (var i = 0; i <= steps; i++) ticks.push(i * step);
    return ticks;
  }

  /* Area + line over an ordered category axis, with a hover crosshair. */
  function lineChart(host, series, opts) {
    var W = 1000, H = opts.height || 260;
    var m = { top: 14, right: 18, bottom: 26, left: 66 };
    var svg = svgRoot(host, W, H);
    var innerW = W - m.left - m.right;
    var innerH = H - m.top - m.bottom;
    var max = Math.max.apply(null, series.map(function (d) { return d.value; }));
    var ticks = niceTicks(max, 4);
    var top = ticks[ticks.length - 1];
    var x = function (i) { return m.left + (series.length === 1 ? innerW / 2 : innerW * i / (series.length - 1)); };
    var y = function (v) { return m.top + innerH - (v / top) * innerH; };

    ticks.forEach(function (t) {
      svg.appendChild(el("line", { x1: m.left, x2: m.left + innerW, y1: y(t), y2: y(t), class: "grid-line" }));
      text(svg, m.left - 10, y(t) + 4, opts.formatTick(t), "tick-text", "end");
    });

    var area = series.map(function (d, i) { return (i ? "L" : "M") + x(i) + "," + y(d.value); }).join("");
    if (opts.fill !== false) {
      svg.appendChild(el("path", {
        d: area + "L" + x(series.length - 1) + "," + y(0) + "L" + x(0) + "," + y(0) + "Z",
        fill: opts.color, "fill-opacity": 0.13
      }));
    }
    svg.appendChild(el("path", { d: area, fill: "none", stroke: opts.color, "stroke-width": 2, "stroke-linejoin": "round" }));

    var hot = el("line", { y1: m.top, y2: m.top + innerH, class: "axis-line", opacity: 0 });
    svg.appendChild(hot);
    var dot = el("circle", { r: 4.5, fill: opts.color, stroke: "var(--surface)", "stroke-width": 2, opacity: 0 });
    svg.appendChild(dot);

    series.forEach(function (d, i) {
      var band = el("rect", {
        x: x(i) - innerW / series.length / 2, y: m.top,
        width: innerW / series.length, height: innerH, fill: "transparent"
      });
      band.addEventListener("mouseenter", function (e) {
        hot.setAttribute("x1", x(i)); hot.setAttribute("x2", x(i)); hot.setAttribute("opacity", 1);
        dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(d.value)); dot.setAttribute("opacity", 1);
        showTip(e, tipRows(d.label, d.tip));
      });
      band.addEventListener("mousemove", moveTip);
      band.addEventListener("mouseleave", function () {
        hot.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); hideTip();
      });
      svg.appendChild(band);
      if (i % opts.labelEvery === 0 || i === series.length - 1) {
        text(svg, x(i), H - 8, d.label, "tick-text", "middle");
      }
    });
    svg.appendChild(el("line", { x1: m.left, x2: m.left + innerW, y1: y(0), y2: y(0), class: "axis-line" }));
  }

  /* Vertical bars that can go negative, coloured by sign. */
  function divergingBars(host, series, opts) {
    var W = 1000, H = opts.height || 130;
    var m = { top: 12, right: 18, bottom: 22, left: 66 };
    var svg = svgRoot(host, W, H);
    var innerW = W - m.left - m.right;
    var innerH = H - m.top - m.bottom;
    var bound = Math.max.apply(null, series.map(function (d) { return Math.abs(d.value); })) || 1;
    var zero = m.top + innerH / 2;
    var slot = innerW / series.length;
    var barW = Math.max(3, slot - 3);

    svg.appendChild(el("line", { x1: m.left, x2: m.left + innerW, y1: zero, y2: zero, class: "axis-line" }));
    text(svg, m.left - 10, zero + 4, "0%", "tick-text", "end");
    text(svg, m.left - 10, m.top + 10, "+" + Math.round(bound) + "%", "tick-text", "end");
    text(svg, m.left - 10, m.top + innerH, "-" + Math.round(bound) + "%", "tick-text", "end");

    series.forEach(function (d, i) {
      var h = Math.abs(d.value) / bound * (innerH / 2);
      var up = d.value >= 0;
      var bx = m.left + i * slot + (slot - barW) / 2;
      var node = el("path", {
        d: up ? barPath(bx, zero - h, barW, h, 3, false) : barPathDown(bx, zero, barW, h, 3),
        fill: up ? "var(--good)" : "var(--bad)",
        class: "mark" + (d.partial ? " partial" : "")
      });
      bindTip(node, tipRows(d.label, d.tip));
      svg.appendChild(node);
    });
  }

  /* Horizontal bars: the default for ranked categories with readable names. */
  function barsH(host, series, opts) {
    // a narrower viewBox in a half-width panel keeps the type from scaling down to nothing
    var W = opts.width || 1000;
    var rowH = opts.rowHeight || 44;
    var barH = opts.barHeight || 15;
    var m = { top: 4, right: opts.right || 96, bottom: 6, left: 0 };
    var H = m.top + m.bottom + series.length * rowH;
    var svg = svgRoot(host, W, H);
    var innerW = W - m.left - m.right;
    var max = Math.max.apply(null, series.map(function (d) { return Math.abs(d.value); })) || 1;

    series.forEach(function (d, i) {
      var y = m.top + i * rowH;
      var barY = y + rowH - barH - 7;
      var w = Math.max(2, Math.abs(d.value) / max * innerW);

      text(svg, m.left, y + 13, d.label, "cat-label");
      if (d.aside) text(svg, W, y + 13, d.aside, "tick-text", "end");

      svg.appendChild(el("rect", {
        x: m.left, y: barY, width: innerW, height: barH, rx: 4, class: "track-fill"
      }));
      var node = el("path", {
        d: barPath(m.left, barY, w, barH, 4, true),
        fill: d.color || opts.color,
        class: "mark"
      });
      bindTip(node, tipRows(d.label, d.tip));
      svg.appendChild(node);
      text(svg, Math.min(m.left + w + 10, W - 4), barY + barH - 3, d.display, "strong-label");
    });
  }

  /* Sequential heatmap. Used for both the RFM grid and the cohort matrix. */
  function heatmap(host, cells, opts) {
    var W = opts.width || 1000;
    var cols = opts.cols, rows = opts.rows;
    var m = { top: 24, right: 12, bottom: 12, left: opts.labelWidth || 78 };
    var cellW = (W - m.left - m.right) / cols.length;
    var cellH = opts.cellHeight || 26;
    var H = m.top + m.bottom + rows.length * cellH;
    var svg = svgRoot(host, W, H);
    var ramp = opts.ramp;
    var max = Math.max.apply(null, cells.map(function (c) { return c.value; })) || 1;

    cols.forEach(function (c, i) {
      text(svg, m.left + i * cellW + cellW / 2, 15, c, "tick-text", "middle");
    });
    rows.forEach(function (r, j) {
      text(svg, m.left - 9, m.top + j * cellH + cellH / 2 + 4, r, "tick-text", "end");
    });

    cells.forEach(function (c) {
      var i = cols.indexOf(c.col);
      var j = rows.indexOf(c.row);
      if (i < 0 || j < 0) return;
      var ratio = opts.scaleMax ? c.value / opts.scaleMax : c.value / max;
      var step = ramp[Math.min(ramp.length - 1, Math.max(0, Math.floor(ratio * ramp.length - 1e-9)))];
      var node = el("rect", {
        x: m.left + i * cellW, y: m.top + j * cellH,
        width: cellW, height: cellH, rx: 3,
        fill: step, class: "mark cell-stroke"
      });
      bindTip(node, tipRows(c.title, c.tip));
      svg.appendChild(node);
      if (opts.showValue && cellW > 34) {
        var label = text(svg, m.left + i * cellW + cellW / 2, m.top + j * cellH + cellH / 2 + 4,
          opts.showValue(c), "value-label", "middle");
        // inline style, because the class's fill would beat a presentation attribute here
        label.style.fill = isLight(step) ? "#0b0b0b" : "#ffffff";
        label.style.pointerEvents = "none";
      }
    });
  }

  /* Cumulative-share curve on a single 0-100 axis, with the 80% crossing called out. */
  function paretoChart(host, points, opts) {
    var W = 1000, H = opts.height || 280;
    var m = { top: 16, right: 20, bottom: 34, left: 52 };
    var svg = svgRoot(host, W, H);
    var innerW = W - m.left - m.right;
    var innerH = H - m.top - m.bottom;
    var maxRank = points[points.length - 1].rank;
    var x = function (r) { return m.left + (r / maxRank) * innerW; };
    var y = function (v) { return m.top + innerH - (v / 100) * innerH; };

    [0, 25, 50, 75, 100].forEach(function (t) {
      svg.appendChild(el("line", { x1: m.left, x2: m.left + innerW, y1: y(t), y2: y(t), class: "grid-line" }));
      text(svg, m.left - 9, y(t) + 4, t + "%", "tick-text", "end");
    });

    var path = points.map(function (p, i) { return (i ? "L" : "M") + x(p.rank) + "," + y(p.value); }).join("");
    svg.appendChild(el("path", {
      d: path + "L" + x(maxRank) + "," + y(0) + "L" + x(points[0].rank) + "," + y(0) + "Z",
      fill: "var(--series-1)", "fill-opacity": 0.12
    }));
    svg.appendChild(el("path", { d: path, fill: "none", stroke: "var(--series-1)", "stroke-width": 2 }));

    svg.appendChild(el("line", {
      x1: m.left, x2: m.left + innerW, y1: y(80), y2: y(80),
      stroke: "var(--warn)", "stroke-width": 1.5, "stroke-dasharray": "5 4"
    }));
    text(svg, m.left + innerW, y(80) - 8, "80% of revenue", "axis-title", "end")
      .setAttribute("fill", "var(--warn)");

    svg.appendChild(el("line", {
      x1: x(opts.rankAt80), x2: x(opts.rankAt80), y1: y(80), y2: y(0),
      stroke: "var(--warn)", "stroke-width": 1.5, "stroke-dasharray": "5 4"
    }));
    svg.appendChild(el("circle", {
      cx: x(opts.rankAt80), cy: y(80), r: 5,
      fill: "var(--warn)", stroke: "var(--surface)", "stroke-width": 2
    }));

    text(svg, m.left, H - 6, "1", "tick-text", "start");
    text(svg, x(opts.rankAt80), H - 6, opts.rankAt80.toLocaleString() + " SKUs", "tick-text", "middle");
    text(svg, W - m.right, H - 6, maxRank.toLocaleString(), "tick-text", "end");

    points.forEach(function (p, i) {
      if (i % 6) return;
      var band = el("rect", { x: x(p.rank) - 6, y: m.top, width: 12, height: innerH, fill: "transparent" });
      bindTip(band, tipRows("Top " + p.rank.toLocaleString() + " SKUs", [["Cumulative share", p.value.toFixed(2) + "%"]]));
      svg.appendChild(band);
    });
  }

  global.Charts = {
    lineChart: lineChart,
    divergingBars: divergingBars,
    barsH: barsH,
    heatmap: heatmap,
    paretoChart: paretoChart,
    hideTip: hideTip
  };
})(window);
