const summaryPeriodOptions = document.getElementById("summary-period-options");
const summarySpent = document.getElementById("summary-spent");
const summaryIncome = document.getElementById("summary-income");
const summaryAvg = document.getElementById("summary-avg");
const summaryTop = document.getElementById("summary-top");
const summaryComparison = document.getElementById("summary-comparison");
const errorBanner = document.getElementById("error-banner");

let summaryPeriod = "week";

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

async function loadSummary() {
  try {
    const s = await apiCall(`/api/summary?period=${summaryPeriod}`);
    summarySpent.textContent = formatMoney(s.total_spent);
    summaryIncome.textContent = formatMoney(s.total_income);
    summaryAvg.textContent = formatMoney(s.avg_daily_spent);
    summaryTop.textContent = s.top_category ? `${s.top_category}` : "—";

    if (s.previous_total_spent > 0) {
      const diff = s.total_spent - s.previous_total_spent;
      const pct = (Math.abs(diff) / s.previous_total_spent) * 100;
      const direction = diff > 0 ? "more" : diff < 0 ? "less" : "the same as";
      const periodLabel = summaryPeriod === "week" ? "last week" : "last month";
      summaryComparison.textContent =
        diff === 0
          ? `Same spending as ${periodLabel}.`
          : `${pct.toFixed(0)}% ${direction} than ${periodLabel} (${formatMoney(s.previous_total_spent)}).`;
    } else {
      summaryComparison.textContent = "";
    }
  } catch (err) {
    showError(err.message);
  }
}

summaryPeriodOptions.addEventListener("click", (e) => {
  const btn = e.target.closest(".setup-option");
  if (!btn) return;
  summaryPeriod = btn.dataset.period;
  summaryPeriodOptions.querySelectorAll(".setup-option").forEach((b) => {
    b.classList.toggle("active", b.dataset.period === summaryPeriod);
  });
  loadSummary();
});

let lastTrends = [];

function buildChart(trends) {
  const wrap = document.getElementById("trend-chart-wrap");
  const emptyEl = document.getElementById("trend-empty");

  if (trends.length < 2) {
    wrap.innerHTML = "";
    emptyEl.style.display = "block";
    return;
  }
  emptyEl.style.display = "none";

  // Fit the chart to the space actually available (phone, tablet, desktop)
  // and only grow past that — forcing horizontal scroll — once there are
  // enough data points that bars would otherwise become illegibly thin.
  const minBarSlot = 26;
  const containerWidth = wrap.clientWidth || 320;
  const width = Math.max(containerWidth, trends.length * minBarSlot);
  const height = 220;
  const padding = { top: 12, right: 12, bottom: 28, left: 12 };
  const chartHeight = height - padding.top - padding.bottom;
  const maxSpent = Math.max(...trends.map((t) => t.total_spent), 1);
  const barWidth = (width - padding.left - padding.right) / trends.length;

  const formatLabel = (iso) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  const bars = trends
    .map((t, i) => {
      const barHeight = Math.max((t.total_spent / maxSpent) * chartHeight, 1);
      const x = padding.left + i * barWidth;
      const y = padding.top + (chartHeight - barHeight);
      return `
        <rect x="${x + barWidth * 0.15}" y="${y}" width="${barWidth * 0.7}" height="${barHeight}" rx="3" fill="var(--primary)">
          <title>${formatLabel(t.date)}: ${formatMoney(t.total_spent)}</title>
        </rect>
      `;
    })
    .join("");

  const labelIndices = Array.from(new Set([0, Math.floor(trends.length / 2), trends.length - 1]));
  const labels = labelIndices
    .map((i) => {
      const x = padding.left + i * barWidth + barWidth / 2;
      return `<text x="${x}" y="${height - 8}" text-anchor="middle" font-size="11" fill="var(--text-muted)">${formatLabel(trends[i].date)}</text>`;
    })
    .join("");

  // Real pixel width/height (not 100%) so a chart that fits the container
  // renders at its natural size, while one with enough data points to
  // exceed the container genuinely overflows it — scrolling horizontally
  // with legible, fixed-width bars instead of being squashed to fit.
  wrap.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">${bars}${labels}</svg>`;
}

function rerenderChartOnResize() {
  let resizeDebounce = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeDebounce);
    resizeDebounce = setTimeout(() => {
      if (lastTrends.length) buildChart(lastTrends);
    }, 200);
  });
}

async function loadTrends() {
  try {
    lastTrends = await apiCall("/api/trends?days=30");
    buildChart(lastTrends);
  } catch (err) {
    showError(err.message);
  }
}

loadSummary();
loadTrends();
rerenderChartOnResize();
