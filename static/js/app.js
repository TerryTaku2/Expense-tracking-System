const datePicker = document.getElementById("date-picker");
const dateHeading = document.getElementById("date-heading");
const setupView = document.getElementById("setup-view");
const mainView = document.getElementById("main-view");
const setupForm = document.getElementById("setup-form");
const setupAmount = document.getElementById("setup-amount");
const editBalanceBtn = document.getElementById("edit-balance-btn");
const expenseForm = document.getElementById("expense-form");
const expenseDesc = document.getElementById("expense-desc");
const expenseAmount = document.getElementById("expense-amount");
const expenseCategory = document.getElementById("expense-category");
const expenseList = document.getElementById("expense-list");
const emptyState = document.getElementById("empty-state");
const errorBanner = document.getElementById("error-banner");

const balanceAmountEl = document.getElementById("balance-amount");
const balanceSubEl = document.getElementById("balance-sub");
const ringProgressEl = document.getElementById("ring-progress");
const statStartingEl = document.getElementById("stat-starting");
const statSpentEl = document.getElementById("stat-spent");
const statCountEl = document.getElementById("stat-count");
const breakdownWrap = document.getElementById("breakdown-wrap");
const breakdownBar = document.getElementById("breakdown-bar");
const breakdownLegend = document.getElementById("breakdown-legend");

const setupOptions = document.getElementById("setup-options");
const newBalanceField = document.getElementById("new-balance-field");
const carryPreview = document.getElementById("carry-preview");
const carryAmountEl = document.getElementById("carry-amount");
const carryDateEl = document.getElementById("carry-date");
const addAmountField = document.getElementById("add-amount-field");
const addAmountInput = document.getElementById("add-amount");
const addPreviewEl = document.getElementById("add-preview");
const setupSubmitBtn = document.getElementById("setup-submit-btn");

const RING_CIRCUMFERENCE = 2 * Math.PI * 52;
ringProgressEl.style.strokeDasharray = `${RING_CIRCUMFERENCE}`;

let lastRenderedBalance = null;
let previousDayData = null;
let setupMode = "new";

const ENCOURAGEMENTS = [
  "Nice, logged! 📝",
  "Tracked it! 👍",
  "Every expense counts. 💪",
  "Staying on top of it! ✨",
];

function todayISO() {
  const d = new Date();
  const offset = d.getTimezoneOffset();
  return new Date(d.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function formatMoney(value) {
  return `$${Number(value).toFixed(2)}`;
}

function formatDateHeading(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = todayISO();
  const prefix = iso === today ? "Today · " : "";
  return prefix + date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

function clearError() {
  errorBanner.classList.remove("visible");
}

async function apiCall(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "Something went wrong");
  }
  return data;
}

async function loadCategories() {
  const categories = await apiCall("/api/categories");
  const datalist = document.getElementById("category-suggestions");
  datalist.innerHTML = categories.map((c) => `<option value="${c}"></option>`).join("");
}

async function loadDay(dateStr) {
  clearError();
  dateHeading.textContent = formatDateHeading(dateStr);
  const day = await apiCall(`/api/day/${dateStr}`);

  if (day.starting_balance === null) {
    setupView.style.display = "block";
    mainView.style.display = "none";
    setupAmount.value = "";
    lastRenderedBalance = null;
    initSetupOptions(day.previous_day);
    return;
  }

  setupView.style.display = "none";
  mainView.style.display = "block";
  renderDay(day);
}

function initSetupOptions(previous) {
  previousDayData = previous;

  if (previous) {
    document.getElementById("carry-option").style.display = "inline-flex";
    document.getElementById("add-option").style.display = "inline-flex";
    carryAmountEl.textContent = formatMoney(previous.balance);
    carryAmountEl.classList.toggle("negative", previous.balance < 0);
    carryDateEl.textContent = formatDateHeading(previous.date).replace("Today · ", "");
  } else {
    document.getElementById("carry-option").style.display = "none";
    document.getElementById("add-option").style.display = "none";
  }

  addAmountInput.value = "";
  setSetupMode("new");
}

function setSetupMode(mode) {
  setupMode = mode;
  setupOptions.querySelectorAll(".setup-option").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
  newBalanceField.style.display = mode === "new" ? "flex" : "none";
  carryPreview.style.display = mode === "carry" ? "block" : "none";
  addAmountField.style.display = mode === "add" ? "flex" : "none";
  setupSubmitBtn.textContent = mode === "carry" ? "Carry over & start" : "Start the day";
  if (mode === "add") updateAddPreview();
}

function updateAddPreview() {
  const addValue = parseFloat(addAmountInput.value);
  if (!previousDayData) return;
  if (!isNaN(addValue)) {
    addPreviewEl.textContent = `${formatMoney(previousDayData.balance)} + ${formatMoney(addValue)} = ${formatMoney(previousDayData.balance + addValue)}`;
  } else {
    addPreviewEl.textContent = `Starting from ${formatMoney(previousDayData.balance)}`;
  }
}

setupOptions.addEventListener("click", (e) => {
  const btn = e.target.closest(".setup-option");
  if (!btn) return;
  setSetupMode(btn.dataset.mode);
});

addAmountInput.addEventListener("input", updateAddPreview);

// Animates the on-screen number counting from its current value to `target`
// so updates feel alive instead of just snapping to a new figure.
function animateBalance(target) {
  const start = lastRenderedBalance === null ? target : lastRenderedBalance;
  lastRenderedBalance = target;
  const duration = 500;
  const startTime = performance.now();

  function tick(now) {
    const progress = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = start + (target - start) * eased;
    balanceAmountEl.textContent = formatMoney(value);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function renderDay(day) {
  const balance = day.balance;
  const state = balance < 0 ? "negative" : balance === day.starting_balance ? "neutral" : "positive";

  animateBalance(balance);
  balanceAmountEl.classList.remove("positive", "negative", "neutral");
  balanceAmountEl.classList.add(state);

  statStartingEl.textContent = formatMoney(day.starting_balance);
  statSpentEl.textContent = formatMoney(day.total_spent);
  statCountEl.textContent = day.expenses.length;

  const remainingFraction = day.starting_balance > 0 ? Math.max(0, Math.min(1, balance / day.starting_balance)) : 0;
  const offset = RING_CIRCUMFERENCE * (1 - remainingFraction);
  ringProgressEl.style.strokeDashoffset = `${offset}`;
  ringProgressEl.classList.remove("ring-warning", "ring-danger");

  const pctSpent = day.starting_balance > 0 ? Math.min(100, (day.total_spent / day.starting_balance) * 100) : 100;
  if (balance < 0) {
    ringProgressEl.classList.add("ring-danger");
    balanceSubEl.textContent = `You've gone over budget by ${formatMoney(Math.abs(balance))}`;
  } else if (pctSpent >= 75) {
    ringProgressEl.classList.add("ring-warning");
    balanceSubEl.textContent = `${pctSpent.toFixed(0)}% of starting balance spent`;
  } else {
    balanceSubEl.textContent = `${pctSpent.toFixed(0)}% of starting balance spent`;
  }

  renderExpenses(day.expenses);
  renderBreakdown(day.expenses, day.total_spent);
}

function renderBreakdown(expenses, totalSpent) {
  if (!expenses.length || totalSpent <= 0) {
    breakdownWrap.style.display = "none";
    return;
  }
  breakdownWrap.style.display = "block";

  const totals = {};
  for (const e of expenses) {
    totals[e.category] = (totals[e.category] || 0) + e.amount;
  }
  const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);

  breakdownBar.innerHTML = sorted
    .map(([category, amount]) => {
      const pct = (amount / totalSpent) * 100;
      const color = colorForCategory(category);
      return `<span class="breakdown-segment" style="width:${pct}%; background:${color};" title="${escapeHtml(category)}: ${formatMoney(amount)}"></span>`;
    })
    .join("");

  breakdownLegend.innerHTML = sorted
    .map(([category, amount]) => {
      const pct = (amount / totalSpent) * 100;
      const color = colorForCategory(category);
      return `
        <div class="legend-item">
          <span class="category-dot" style="background:${color}"></span>
          <span>${escapeHtml(category)}</span>
          <span class="legend-amount">${formatMoney(amount)} · ${pct.toFixed(0)}%</span>
        </div>
      `;
    })
    .join("");
}

function renderExpenses(expenses) {
  if (!expenses.length) {
    expenseList.innerHTML = "";
    emptyState.style.display = "block";
    return;
  }
  emptyState.style.display = "none";
  expenseList.innerHTML = expenses
    .map((e, i) => {
      const time = new Date(e.created_at.replace(" ", "T")).toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      });
      const color = colorForCategory(e.category);
      return `
        <li class="expense-item" style="animation-delay:${Math.min(i, 8) * 30}ms">
          <span class="category-dot" style="background:${color}"></span>
          <div class="expense-info">
            <div class="expense-desc">${escapeHtml(e.description)}</div>
            <div class="expense-meta">${escapeHtml(e.category)} · ${time}</div>
          </div>
          <div class="expense-amount">-${formatMoney(e.amount)}</div>
          <button class="delete-btn" data-id="${e.id}" title="Delete">✕</button>
        </li>
      `;
    })
    .join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function currentDate() {
  return datePicker.value || todayISO();
}

const requestedDate = new URLSearchParams(window.location.search).get("date");
datePicker.value = requestedDate || todayISO();
datePicker.max = todayISO();
datePicker.addEventListener("change", () => {
  lastRenderedBalance = null;
  loadDay(currentDate());
});

setupForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();

  let startingBalance;
  if (setupMode === "new") {
    if (setupAmount.value === "") {
      showError("Enter a starting balance");
      return;
    }
    startingBalance = setupAmount.value;
  } else if (setupMode === "carry") {
    startingBalance = previousDayData.balance;
  } else if (setupMode === "add") {
    const addValue = parseFloat(addAmountInput.value);
    if (isNaN(addValue) || addValue <= 0) {
      showError("Enter an amount to add");
      return;
    }
    startingBalance = previousDayData.balance + addValue;
  }

  try {
    await apiCall("/api/day", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: currentDate(), starting_balance: startingBalance }),
    });
    await loadDay(currentDate());
    showToast("Day started — let's track it! 🎯", { type: "success" });
    loadStreak({ celebrateOnIncrease: true });
  } catch (err) {
    showError(err.message);
  }
});

editBalanceBtn.addEventListener("click", () => {
  const newValue = prompt("Set a new starting balance for this day:");
  if (newValue === null) return;
  apiCall("/api/day", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: currentDate(), starting_balance: newValue }),
  })
    .then(() => loadDay(currentDate()))
    .then(() => loadStreak({ celebrateOnIncrease: true }))
    .catch((err) => showError(err.message));
});

expenseForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiCall("/api/expenses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: currentDate(),
        description: expenseDesc.value,
        amount: expenseAmount.value,
        category: expenseCategory.value,
      }),
    });
    expenseDesc.value = "";
    expenseAmount.value = "";
    expenseCategory.value = "";
    expenseDesc.focus();
    await Promise.all([loadDay(currentDate()), loadCategories()]);
    showToast(ENCOURAGEMENTS[Math.floor(Math.random() * ENCOURAGEMENTS.length)]);
    loadStreak({ celebrateOnIncrease: true });
  } catch (err) {
    showError(err.message);
  }
});

expenseList.addEventListener("click", async (e) => {
  const btn = e.target.closest(".delete-btn");
  if (!btn) return;
  try {
    await apiCall(`/api/expenses/${btn.dataset.id}`, { method: "DELETE" });
    await loadDay(currentDate());
    loadStreak({ celebrateOnIncrease: true });
  } catch (err) {
    showError(err.message);
  }
});

(async function init() {
  await loadCategories();
  await loadDay(currentDate());
})();
