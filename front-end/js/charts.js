/* ═════════════════════════════════════════════════════════════════════════
   MedAI Hospital — Chart helpers (Chart.js wrappers)
   ═════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const PALETTE = [
    "#00355f", "#0369a1", "#00695c", "#b45309", "#ba1a1a",
    "#0f4c81", "#0284c7", "#0d9488", "#d97706", "#9a3412",
    "#1e3a8a", "#0891b2", "#065f46", "#92400e", "#7c2d12",
  ];
  const TEXT_COLOR = "#334155";
  const GRID_COLOR = "rgba(148, 163, 184, 0.22)";

  const BASE_OPTS = () => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: "bottom",
        labels: { color: TEXT_COLOR, font: { size: 11 }, boxWidth: 12 },
      },
      tooltip: {
        backgroundColor: "rgba(15, 23, 42, 0.92)",
        padding: 10,
        titleFont: { size: 12, weight: "600" },
        bodyFont: { size: 12 },
      },
    },
  });

  const AXIS_OPTS = () => ({
    ticks: { color: TEXT_COLOR, font: { size: 11 } },
    grid: { color: GRID_COLOR },
  });

  // Destruye el grafico previo si existia, y crea uno nuevo en el canvas
  function mount(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    if (canvas._chart) { try { canvas._chart.destroy(); } catch (_) {} }
    canvas._chart = new window.Chart(canvas, config);
    return canvas._chart;
  }

  function toLabelsAndValues(items, labelMapper) {
    const labels = (items || []).map(x => labelMapper ? labelMapper(x.name) : x.name);
    const values = (items || []).map(x => x.count);
    return { labels, values };
  }

  // ─── Bar chart ─────────────────────────────────────────────────────
  function bar(canvasId, items, { title = "", labelMapper, horizontal = false } = {}) {
    const { labels, values } = toLabelsAndValues(items, labelMapper);
    return mount(canvasId, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: title,
          data: values,
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderRadius: 6,
          borderSkipped: false,
        }],
      },
      options: {
        ...BASE_OPTS(),
        indexAxis: horizontal ? "y" : "x",
        plugins: {
          ...BASE_OPTS().plugins,
          legend: { display: false },
          title: title ? { display: true, text: title, color: TEXT_COLOR } : { display: false },
        },
        scales: {
          x: AXIS_OPTS(),
          y: AXIS_OPTS(),
        },
      },
    });
  }

  // ─── Doughnut chart ────────────────────────────────────────────────
  function doughnut(canvasId, items, { labelMapper } = {}) {
    const { labels, values } = toLabelsAndValues(items, labelMapper);
    return mount(canvasId, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderColor: "#ffffff",
          borderWidth: 2,
        }],
      },
      options: {
        ...BASE_OPTS(),
        cutout: "62%",
      },
    });
  }

  // ─── Pie chart ─────────────────────────────────────────────────────
  function pie(canvasId, items, { labelMapper } = {}) {
    const { labels, values } = toLabelsAndValues(items, labelMapper);
    return mount(canvasId, {
      type: "pie",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderColor: "#ffffff",
          borderWidth: 2,
        }],
      },
      options: BASE_OPTS(),
    });
  }

  // ─── Line / Area chart ─────────────────────────────────────────────
  function line(canvasId, items, { title = "", labelMapper } = {}) {
    const { labels, values } = toLabelsAndValues(items, labelMapper);
    return mount(canvasId, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: title,
          data: values,
          borderColor: PALETTE[0],
          backgroundColor: "rgba(0, 53, 95, 0.12)",
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          pointBackgroundColor: PALETTE[0],
        }],
      },
      options: {
        ...BASE_OPTS(),
        plugins: {
          ...BASE_OPTS().plugins,
          legend: { display: false },
        },
        scales: { x: AXIS_OPTS(), y: AXIS_OPTS() },
      },
    });
  }

  window.ChartKit = { bar, doughnut, pie, line, mount, PALETTE };
})();
