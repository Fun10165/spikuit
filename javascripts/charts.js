/**
 * Spikuit concept diagrams — Chart.js renderers.
 *
 * Each <canvas data-chart="name"> is auto-rendered on page load.
 * Re-renders on MkDocs Material theme toggle (light/dark).
 */

/* ------------------------------------------------------------------ */
/*  Palette                                                            */
/* ------------------------------------------------------------------ */

function getColors() {
  var dark =
    document.body.getAttribute("data-md-color-scheme") === "slate";
  return {
    text:      dark ? "#ccc" : "#555",
    grid:      dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.08)",
    ltp:       "#4CAF50",
    ltd:       "#E53935",
    pressure:  "#7C4DFF",
    threshold: "#FF9800",
    decay:     dark ? "#777" : "#BDBDBD",
    review:    "#2196F3",
    fire:      "#4CAF50",
  };
}

/* ------------------------------------------------------------------ */
/*  Bootstrap                                                          */
/* ------------------------------------------------------------------ */

function initCharts() {
  if (typeof Chart === "undefined") {
    return setTimeout(initCharts, 100);
  }

  document.querySelectorAll("canvas[data-chart]").forEach(function (el) {
    var existing = Chart.getChart(el);
    if (existing) existing.destroy();

    var fn = {
      stdp: renderSTDP,
      lif: renderLIF,
      "forgetting-curve": renderForgettingCurve,
    }[el.dataset.chart];
    if (fn) fn(el);
  });
}

document.addEventListener("DOMContentLoaded", initCharts);

// MkDocs Material instant-navigation support
if (typeof document$ !== "undefined") {
  document$.subscribe(function () { initCharts(); });
}

// Re-render on theme toggle
new MutationObserver(initCharts).observe(document.body, {
  attributes: true,
  attributeFilter: ["data-md-color-scheme"],
});

/* ------------------------------------------------------------------ */
/*  Shared chart factory                                               */
/* ------------------------------------------------------------------ */

function makeChart(canvas, datasets, xLabel, yLabel, overrides) {
  var c = getColors();
  var o = overrides || {};

  return new Chart(canvas, {
    type: "scatter",
    data: { datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: o.aspectRatio || 2.0,
      layout: {
        padding: { top: 12, right: 20, bottom: 8, left: 8 },
      },
      animation: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: c.text,
            usePointStyle: true,
            pointStyle: "line",
            padding: 20,
            font: { size: 11 },
          },
        },
        tooltip: { enabled: false },
      },
      scales: {
        x: {
          type: "linear",
          min: o.xMin,
          max: o.xMax,
          title: {
            display: !!xLabel,
            text: xLabel,
            color: c.text,
            padding: { top: 12 },
            font: { size: 11 },
          },
          ticks: {
            color: c.text,
            font: { size: 10 },
            maxTicksLimit: 7,
            padding: 6,
          },
          grid: { color: c.grid },
          border: { color: c.grid },
        },
        y: {
          min: o.yMin,
          max: o.yMax,
          title: {
            display: !!yLabel,
            text: yLabel,
            color: c.text,
            padding: { bottom: 12 },
            font: { size: 11 },
          },
          ticks: {
            color: c.text,
            font: { size: 10 },
            maxTicksLimit: 6,
            padding: 8,
            stepSize: o.yStep,
          },
          grid: { color: c.grid },
          border: { color: c.grid },
        },
      },
    },
  });
}

/* ------------------------------------------------------------------ */
/*  Dataset helper                                                     */
/* ------------------------------------------------------------------ */

function line(label, data, color, opts) {
  var d = {
    label: label,
    data: data,
    showLine: true,
    borderColor: color,
    borderWidth: 2.5,
    pointRadius: 0,
    fill: false,
  };
  if (opts) {
    for (var k in opts) d[k] = opts[k];
  }
  return d;
}

/* ------------------------------------------------------------------ */
/*  STDP                                                               */
/* ------------------------------------------------------------------ */

function renderSTDP(canvas) {
  var c = getColors();
  var tau = 7, aPlus = 1.0, aMinus = 0.8;

  var ltp = [], ltd = [];
  for (var dt = -7; dt <= 0; dt += 0.15) {
    ltp.push({ x: dt, y: aPlus * Math.exp(-Math.abs(dt) / tau) });
  }
  for (var dt2 = 0; dt2 <= 7; dt2 += 0.15) {
    ltd.push({ x: dt2, y: -aMinus * Math.exp(-Math.abs(dt2) / tau) });
  }

  makeChart(
    canvas,
    [
      line("LTP (strengthen)", ltp, c.ltp),
      line("LTD (weaken)", ltd, c.ltd),
    ],
    "\u0394t (days)", "\u0394w",
    { aspectRatio: 1.6, xMin: -8, xMax: 8, yMin: -1.2, yMax: 1.2, yStep: 0.4 }
  );
}

/* ------------------------------------------------------------------ */
/*  LIF                                                                */
/* ------------------------------------------------------------------ */

function renderLIF(canvas) {
  var c = getColors();
  var tauM = 6, fires = [5, 14, 23], threshVal = 0.65;

  var pts = [], pressure = 0.1;
  for (var t = 0; t <= 32; t += 0.25) {
    for (var f = 0; f < fires.length; f++) {
      if (Math.abs(t - fires[f]) < 0.25) pressure += 0.55;
    }
    pts.push({ x: t, y: pressure });
    pressure *= Math.exp(-0.25 / tauM);
  }

  var thLine = [{ x: 0, y: threshVal }, { x: 34, y: threshVal }];

  makeChart(
    canvas,
    [
      line("pressure", pts, c.pressure),
      line("threshold", thLine, c.threshold, { borderWidth: 1.5, borderDash: [6, 4] }),
    ],
    "time", "pressure",
    { xMin: 0, xMax: 34, yMin: 0, yMax: 1.0, yStep: 0.2 }
  );
}

/* ------------------------------------------------------------------ */
/*  Forgetting Curve                                                   */
/* ------------------------------------------------------------------ */

function renderForgettingCurve(canvas) {
  var c = getColors();
  var stability0 = 8;

  var noReview = [];
  for (var t = 0; t <= 60; t += 0.5) {
    noReview.push({ x: t, y: 100 * Math.exp(-t / stability0) });
  }

  var reviews = [12, 28, 50];
  var stabs = [8, 16, 32, 60];
  var spaced = [], recall = 100, stab = stabs[0], last = 0, ri = 0;

  for (var t2 = 0; t2 <= 60; t2 += 0.5) {
    if (ri < reviews.length && t2 >= reviews[ri]) {
      recall = 100;
      last = reviews[ri];
      ri++;
      stab = stabs[ri];
    }
    spaced.push({ x: t2, y: recall * Math.exp(-(t2 - last) / stab) });
  }

  var markers = reviews.map(function (r) { return { x: r, y: 100 }; });

  makeChart(
    canvas,
    [
      line("with review", spaced, c.review),
      line("without review", noReview, c.decay, { borderWidth: 1.8, borderDash: [6, 4] }),
      {
        label: "review",
        data: markers,
        showLine: false,
        borderColor: c.fire,
        backgroundColor: c.fire,
        pointRadius: 5,
        pointStyle: "triangle",
      },
    ],
    "time (days)", "recall %",
    { xMin: 0, xMax: 65, yMin: 0, yMax: 110, yStep: 20 }
  );
}
