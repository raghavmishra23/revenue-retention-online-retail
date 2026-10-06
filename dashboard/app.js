/* Reads the exported mart payload and renders the three pages. Nothing is recomputed
   here beyond formatting and row selection: every figure arrives calculated in SQL. */
(function () {
  "use strict";

  var SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var DEFAULTS = { region: "all", topn: "10", cohort: "12" };

  var data = window.DASHBOARD_DATA || null;
  var symbol = "";
  var filters = Object.assign({}, DEFAULTS);

  /* Formatting ------------------------------------------------------- */

  function money(value, digits) {
    var abs = Math.abs(value);
    var sign = value < 0 ? "-" : "";
    if (abs >= 1e7) return sign + symbol + (abs / 1e7).toFixed(digits === undefined ? 2 : digits) + " cr";
    if (abs >= 1e5) return sign + symbol + (abs / 1e5).toFixed(2) + " L";
    if (abs >= 1e3) return sign + symbol + Math.round(abs).toLocaleString("en-IN");
    return sign + symbol + abs.toFixed(2);
  }

  function exact(value) {
    return (value < 0 ? "-" : "") + symbol + Math.abs(value).toLocaleString("en-IN", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function count(value) { return Number(value).toLocaleString("en-IN"); }
  function pct(value, digits) { return Number(value).toFixed(digits === undefined ? 1 : digits) + "%"; }

  function monthLabel(ym) {
    var parts = ym.split("-");
    return MONTHS[parseInt(parts[1], 10) - 1] + " " + parts[0].slice(2);
  }

  function fullMonth(ym) {
    var parts = ym.split("-");
    return MONTHS[parseInt(parts[1], 10) - 1] + " " + parts[0];
  }

  function setText(id, value) { document.getElementById(id).textContent = value; }
  function setHTML(id, value) { document.getElementById(id).innerHTML = value; }

  function chip(id, tone, label) {
    var node = document.getElementById(id);
    node.className = "chip " + tone;
    node.textContent = label;
  }

  function statCard(label, value, note, tone, chipLabel) {
    return '<div class="card"><div class="stat-label">' + label + "</div>" +
      '<div class="stat-value">' + value + "</div>" +
      '<div class="stat-note">' + note + "</div>" +
      (chipLabel ? '<span class="chip ' + tone + '">' + chipLabel + "</span>" : "") +
      "</div>";
  }

  function legend(host, items) {
    setHTML(host, items.map(function (it) {
      return '<span class="legend-item"><span class="legend-swatch" style="background:' +
        it.color + '"></span>' + it.label + "</span>";
    }).join(""));
  }

  function rampLegend(host, low, high) {
    setHTML(host, '<span class="legend-item">' + low + '<span class="legend-ramp">' +
      SEQ.map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("") +
      "</span>" + high + "</span>");
  }

  function table(host, columns, rows) {
    setHTML(host,
      "<thead><tr>" + columns.map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead>" +
      "<tbody>" + rows.map(function (r) {
        return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody>");
  }

  function partialMonth() {
    return data.revenue_trend[data.revenue_trend.length - 1].year_month;
  }

  /* Overview ---------------------------------------------------------- */

  function visibleCountries() {
    var rows = data.countries.filter(function (c) {
      return filters.region === "all" || c.region === filters.region;
    });
    var limit = parseInt(filters.topn, 10);
    return limit > 0 ? rows.slice(0, limit) : rows;
  }

  function renderHero() {
    var k = data.kpis;
    setText("hero-value", money(k.net_revenue));
    setHTML("hero-note", exact(k.gross_revenue) + " gross less " + exact(-k.returns) +
      " returned, across " + count(k.active_customers) + " identified customers");
    chip("hero-chip", k.revenue_yoy_pct >= 0 ? "good" : "bad",
      (k.revenue_yoy_pct >= 0 ? "▲ " : "▼ ") + pct(Math.abs(k.revenue_yoy_pct), 2) +
      " year on year");

    setText("stat-return", pct(k.return_rate_pct, 2));
    setHTML("stat-return-note", exact(-k.returns) + " booked out of " + exact(k.gross_revenue));
    chip("stat-return-chip", "warn",
      pct(data.same_day_reversals.value / k.returns * 100) + " is same-day reversal");

    setText("stat-orders", count(k.orders));
    setHTML("stat-orders-note", "Average order value " + exact(k.aov));
    chip("stat-orders-chip", "good", pct(k.repeat_purchase_rate_pct) + " repeat buyers");
  }

  function renderTrend() {
    var partial = partialMonth();
    legend("trend-legend", [
      { color: "var(--series-1)", label: "Net revenue" },
      { color: "var(--good)", label: "Growth" },
      { color: "var(--bad)", label: "Decline" }
    ]);

    Charts.lineChart(document.getElementById("chart-trend"), data.revenue_trend.map(function (m) {
      return {
        label: monthLabel(m.year_month),
        value: m.net_revenue,
        tip: [
          ["Net revenue", exact(m.net_revenue)],
          ["Gross", exact(m.gross_revenue)],
          ["Returns", exact(m.returns)],
          ["Orders", count(m.orders)],
          ["AOV", exact(m.aov)],
          ["Return rate", pct(m.return_rate_pct, 2)]
        ]
      };
    }), {
      color: "var(--series-1)",
      labelEvery: 3,
      formatTick: function (v) { return money(v, 1); },
      height: 250,
      fill: document.getElementById("trend-type").value === "area"
    });

    Charts.divergingBars(document.getElementById("chart-mom"), data.revenue_trend
      .filter(function (m) { return m.net_revenue_mom_pct !== null; })
      .map(function (m) {
        return {
          label: monthLabel(m.year_month),
          value: m.net_revenue_mom_pct,
          partial: m.year_month === partial,
          tip: [["MoM change", pct(m.net_revenue_mom_pct, 2)], ["Net revenue", exact(m.net_revenue)]]
        };
      }), { height: 118 });

    setHTML("partial-month-note",
      "<strong>" + fullMonth(partial) + " is a partial month</strong> — the data stops on " +
      "9 December 2011, so its total and its " + pct(data.kpis.revenue_mom_pct, 1) +
      " month-over-month fall reflect a shorter month, not a collapse in trade. It is dimmed " +
      "below and excluded from the year-on-year figure.");
  }

  function renderMarkets() {
    var rows = visibleCountries();
    Charts.barsH(document.getElementById("chart-countries"), rows.map(function (c) {
      return {
        label: c.country,
        aside: count(c.orders) + " orders",
        value: c.net_revenue,
        display: money(c.net_revenue),
        color: c.revenue_rank === 1 ? "var(--series-1)" : "var(--seq-2)",
        tip: [
          ["Net revenue", exact(c.net_revenue)],
          ["Orders", count(c.orders)],
          ["Customers", count(c.customers)],
          ["AOV", exact(c.aov)],
          ["Return rate", pct(c.return_rate_pct, 2)]
        ]
      };
    }), { width: 620, rowHeight: 42, right: 110 });

    table("country-table", ["Market", "Region", "Net revenue", "Orders", "Return rate"],
      rows.map(function (c) {
        return [c.country, c.region, exact(c.net_revenue), count(c.orders),
          pct(c.return_rate_pct, 2)];
      }));

    Charts.barsH(document.getElementById("chart-regions"), data.regions.map(function (r) {
      return {
        label: r.region,
        aside: count(r.customers) + " customers",
        value: r.net_revenue,
        display: money(r.net_revenue),
        color: "var(--series-1)",
        tip: [["Net revenue", exact(r.net_revenue)], ["Customers", count(r.customers)]]
      };
    }), { width: 560, rowHeight: 42, right: 110 });

    table("region-table", ["Region", "Net revenue", "Customers"], data.regions.map(function (r) {
      return [r.region, exact(r.net_revenue), count(r.customers)];
    }));
  }

  /* Customers ---------------------------------------------------------- */

  function attributableRevenue() {
    return data.rfm_segments.reduce(function (sum, s) { return sum + s.net_revenue; }, 0);
  }

  function renderCustomers() {
    var k = data.kpis;
    var attributable = attributableRevenue();
    var champions = data.rfm_segments.filter(function (s) { return s.segment === "Champions"; })[0];
    var slipping = data.rfm_segments.filter(function (s) {
      return s.segment === "At Risk" || s.segment === "Cannot Lose Them";
    });
    var slippingCustomers = slipping.reduce(function (n, s) { return n + s.customers; }, 0);
    var slippingValue = slipping.reduce(function (n, s) { return n + s.net_revenue; }, 0);

    setHTML("customer-stats", [
      statCard("Identified customers", count(k.active_customers),
        "Guest lines carry revenue but no customer", "", ""),
      statCard("Average customer value", exact(k.average_clv),
        "Net revenue per identified customer", "good",
        pct(k.repeat_purchase_rate_pct) + " buy again"),
      statCard("Champions", count(champions.customers),
        pct(champions.customers / k.active_customers * 100) + " of customers", "good",
        pct(champions.net_revenue / attributable * 100) + " of revenue"),
      statCard("Slipping away", count(slippingCustomers),
        "At Risk plus Cannot Lose Them", "bad", money(slippingValue) + " at stake")
    ].join(""));

    rampLegend("rfm-legend", "fewer&nbsp;", "&nbsp;more");
    var maxCell = Math.max.apply(null, data.rfm_matrix.map(function (c) { return c.customers; }));
    Charts.heatmap(document.getElementById("chart-rfm"), data.rfm_matrix.map(function (c) {
      return {
        col: "F" + c.f_score,
        row: "R" + c.r_score,
        value: c.customers,
        title: "Recency " + c.r_score + " / Frequency " + c.f_score,
        tip: [["Customers", count(c.customers)], ["Net revenue", exact(c.net_revenue)]]
      };
    }), {
      width: 560, cols: ["F1", "F2", "F3", "F4", "F5"], rows: ["R5", "R4", "R3", "R2", "R1"],
      ramp: SEQ, scaleMax: maxCell, labelWidth: 40, cellHeight: 46,
      showValue: function (c) { return count(c.value); }
    });

    renderSegments();
    renderCohort();

    table("segment-table",
      ["Segment", "Customers", "Net revenue", "Share", "Avg value", "Avg orders", "Days since order"],
      data.rfm_segments.map(function (s) {
        return [s.segment, count(s.customers), exact(s.net_revenue),
          pct(s.net_revenue / attributable * 100, 2), exact(s.average_value),
          s.average_orders, s.average_recency_days];
      }));
  }

  function renderSegments() {
    var measure = document.getElementById("segment-measure").value;
    var attributable = attributableRevenue();
    var rows = data.rfm_segments.slice().sort(function (a, b) { return b[measure] - a[measure]; });
    Charts.barsH(document.getElementById("chart-segments"), rows.map(function (s) {
      return {
        label: s.segment,
        aside: count(s.customers) + " customers",
        value: s[measure],
        display: measure === "customers" ? count(s.customers) : money(s.net_revenue),
        color: s.segment === "Champions" ? "var(--series-1)" : "var(--seq-2)",
        tip: [
          ["Customers", count(s.customers)],
          ["Net revenue", exact(s.net_revenue)],
          ["Share of revenue", pct(s.net_revenue / attributable * 100, 2)],
          ["Average value", exact(s.average_value)],
          ["Average orders", s.average_orders],
          ["Days since order", s.average_recency_days]
        ]
      };
    }), { width: 560, rowHeight: 42, right: 110 });
  }

  function renderCohort() {
    var depth = parseInt(filters.cohort, 10);
    var offsets = [];
    for (var i = 0; i <= depth; i++) offsets.push(i);
    var cohorts = [];
    data.cohort.forEach(function (c) {
      if (cohorts.indexOf(c.cohort_month) < 0) cohorts.push(c.cohort_month);
    });
    rampLegend("cohort-legend", "0%&nbsp;", "&nbsp;100% retained");
    Charts.heatmap(document.getElementById("chart-cohort"),
      data.cohort.filter(function (c) { return c.month_offset <= depth; }).map(function (c) {
        return {
          col: "M" + c.month_offset,
          row: monthLabel(c.cohort_month),
          value: c.retention_pct,
          title: monthLabel(c.cohort_month) + " cohort, month " + c.month_offset,
          tip: [
            ["Retention", pct(c.retention_pct, 1)],
            ["Active", count(c.active_customers)],
            ["Cohort size", count(c.cohort_size)]
          ]
        };
      }), {
        cols: offsets.map(function (o) { return "M" + o; }),
        rows: cohorts.map(monthLabel),
        ramp: SEQ, scaleMax: 100, labelWidth: 66, cellHeight: 24,
        showValue: function (c) { return c.value >= 10 ? Math.round(c.value) : ""; }
      });
  }

  /* Products ----------------------------------------------------------- */

  function renderProducts() {
    var p = data.pareto;
    var k = data.kpis;
    var rev = data.same_day_reversals;
    var drivers = data.return_drivers.reduce(function (s, d) { return s + d.returns; }, 0);

    setHTML("product-stats", [
      statCard("SKUs sold", count(p.total_skus), "Product lines only", "", ""),
      statCard("Drive 80% of revenue", count(p.band_skus),
        pct(p.band_skus / p.total_skus * 100) + " of the catalogue", "good",
        money(p.band_net_revenue) + " of net revenue"),
      statCard("The long tail", count(p.total_skus - p.band_skus),
        "SKUs carrying the remaining fifth", "", ""),
      statCard("Value booked out", money(k.returns),
        pct(drivers / k.returns * 100) + " from the top 12 SKUs", "warn",
        pct(rev.value / k.returns * 100) + " same-day reversal")
    ].join(""));

    legend("pareto-legend", [
      { color: "var(--series-1)", label: "Cumulative share" },
      { color: "var(--warn)", label: "80% threshold" }
    ]);

    Charts.paretoChart(document.getElementById("chart-pareto"), p.curve.map(function (c) {
      return { rank: c.revenue_rank, value: c.cumulative_share_pct };
    }), { rankAt80: p.rank_at_80, height: 270 });

    renderTopProducts();

    Charts.barsH(document.getElementById("chart-returns"), data.return_drivers.map(function (d) {
      return {
        label: d.stock_code,
        aside: count(d.return_lines) + (d.return_lines === 1 ? " line" : " lines"),
        value: Math.abs(d.returns),
        display: money(d.returns),
        color: "var(--series-2)",
        tip: [
          ["Returned value", exact(d.returns)],
          ["Return rate", pct(d.return_rate_pct, 2)],
          ["Return lines", count(d.return_lines)]
        ]
      };
    }), { width: 560, rowHeight: 40, right: 100 });

    setHTML("reversal-note",
      "<strong>Not all of this is a customer return.</strong> " + count(rev.lines) +
      " cancellation lines worth " + money(rev.value) + " (" +
      pct(rev.value / k.returns * 100) + " of all returned value) reverse an identical order " +
      "placed the same day by the same customer. Those are order-entry corrections, so read " +
      "this as where value is booked out, not where goods come back.");
  }

  function renderTopProducts() {
    var measure = document.getElementById("product-measure").value;
    var rows = data.top_products.slice().sort(function (a, b) { return b[measure] - a[measure]; });
    Charts.barsH(document.getElementById("chart-products"), rows.map(function (t) {
      return {
        label: t.description.length > 30 ? t.description.slice(0, 29) + "…" : t.description,
        aside: t.stock_code,
        value: t[measure],
        display: measure === "units" ? count(t.units) + " units" : money(t.net_revenue),
        color: "var(--series-1)",
        tip: [
          ["Stock code", t.stock_code],
          ["Description", t.description],
          ["Net revenue", exact(t.net_revenue)],
          ["Units", count(t.units)],
          ["Orders", count(t.orders)]
        ]
      };
    }), { width: 560, rowHeight: 38, right: 100 });
  }

  /* Wiring ------------------------------------------------------------- */

  function populateRegions() {
    var select = document.getElementById("filter-region");
    data.regions.forEach(function (r) {
      var option = document.createElement("option");
      option.value = r.region;
      option.textContent = r.region;
      select.appendChild(option);
    });
  }

  function setupFilters() {
    [["filter-region", "region"], ["filter-topn", "topn"], ["filter-cohort", "cohort"]]
      .forEach(function (pair) {
        document.getElementById(pair[0]).addEventListener("change", function (e) {
          filters[pair[1]] = e.target.value;
          renderMarkets();
          renderCohort();
        });
      });

    document.getElementById("filter-reset").addEventListener("click", function () {
      filters = Object.assign({}, DEFAULTS);
      document.getElementById("filter-region").value = DEFAULTS.region;
      document.getElementById("filter-topn").value = DEFAULTS.topn;
      document.getElementById("filter-cohort").value = DEFAULTS.cohort;
      renderMarkets();
      renderCohort();
    });

    document.getElementById("trend-type").addEventListener("change", renderTrend);
    document.getElementById("segment-measure").addEventListener("change", renderSegments);
    document.getElementById("product-measure").addEventListener("change", renderTopProducts);
  }

  function showPage(name) {
    var tabs = [].slice.call(document.querySelectorAll(".tab"));
    if (!tabs.some(function (t) { return t.dataset.page === name; })) name = tabs[0].dataset.page;
    tabs.forEach(function (t) {
      t.classList.toggle("is-active", t.dataset.page === name);
      t.setAttribute("aria-selected", t.dataset.page === name ? "true" : "false");
    });
    document.querySelectorAll(".page").forEach(function (page) {
      page.classList.toggle("is-active", page.id === "page-" + name);
    });
    Charts.hideTip();
  }

  function setupTabs() {
    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        location.hash = tab.dataset.page;
        showPage(tab.dataset.page);
      });
    });
    window.addEventListener("hashchange", function () {
      showPage(location.hash.replace("#", ""));
    });
    showPage(location.hash.replace("#", ""));
  }

  function renderAll() {
    renderHero();
    renderTrend();
    renderMarkets();
    renderCustomers();
    renderProducts();
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var button = document.getElementById("theme-toggle");
    button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    document.getElementById("theme-icon").innerHTML = theme === "dark" ? "&#9681;" : "&#9728;";
  }

  function setupTheme() {
    var stored = null;
    try { stored = localStorage.getItem("theme"); } catch (e) { stored = null; }
    var asked = new URLSearchParams(location.search).get("theme");
    applyTheme(asked === "light" || asked === "dark" ? asked : (stored === "light" ? "light" : "dark"));
    document.getElementById("theme-toggle").addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
      applyTheme(next);
      // heatmap label contrast is resolved at draw time, so the cells need redrawing
      if (data) renderAll();
      try { localStorage.setItem("theme", next); } catch (e) { /* private browsing */ }
    });
  }

  function boot() {
    setupTheme();
    setupTabs();
    if (!data) {
      document.querySelector("main").innerHTML =
        '<div class="card"><h2>No mart data loaded</h2><p class="card-note">Run ' +
        "<code>python -m src.pipeline dashboard</code> to regenerate " +
        "<code>dashboard/data/dashboard_data.js</code>.</p></div>";
      return;
    }
    symbol = data.meta.currency_symbol;
    setText("subtitle", count(data.kpis.orders) + " orders across " + data.countries.length +
      " markets · " + fullMonth(data.meta.period.start) + " – " +
      fullMonth(data.meta.period.end) + " · all figures in " + data.meta.currency);
    setText("provenance",
      "Built on the UCI Online Retail II transactional dataset, re-badged to an Indian retail " +
      "context with values read as " + data.meta.currency + " and no rate conversion applied. " +
      "Every figure here is computed in SQL against the warehouse and exported; nothing is " +
      "recalculated in the browser.");
    populateRegions();
    setupFilters();
    renderAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
