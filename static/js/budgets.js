const errorBanner = document.getElementById("error-banner");

const budgetForm = document.getElementById("budget-form");
const budgetCategory = document.getElementById("budget-category");
const budgetAmount = document.getElementById("budget-amount");
const budgetPeriod = document.getElementById("budget-period");
const budgetsList = document.getElementById("budgets-list");
const budgetsEmpty = document.getElementById("budgets-empty");

const recurringForm = document.getElementById("recurring-form");
const recurringDesc = document.getElementById("recurring-desc");
const recurringAmount = document.getElementById("recurring-amount");
const recurringCategory = document.getElementById("recurring-category");
const recurringFrequency = document.getElementById("recurring-frequency");
const recurringStart = document.getElementById("recurring-start");
const recurringList = document.getElementById("recurring-list");
const recurringEmpty = document.getElementById("recurring-empty");

function todayISO() {
  const d = new Date();
  const offset = d.getTimezoneOffset();
  return new Date(d.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function formatMoney(value) {
  return `$${Number(value).toFixed(2)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

async function apiCall(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

async function loadCategoriesForSuggestions() {
  const categories = await apiCall("/api/categories");
  document.getElementById("category-suggestions").innerHTML = categories.map((c) => `<option value="${c}"></option>`).join("");
}

function renderBudgets(budgets) {
  if (!budgets.length) {
    budgetsList.innerHTML = "";
    budgetsEmpty.style.display = "block";
    return;
  }
  budgetsEmpty.style.display = "none";

  budgetsList.innerHTML = budgets
    .map((b) => {
      const color = colorForCategory(b.category);
      const barClass = b.pct >= 100 ? "danger" : b.pct >= 75 ? "warning" : "";
      const metaText =
        b.remaining >= 0
          ? `${formatMoney(b.spent)} of ${formatMoney(b.amount)} spent · ${formatMoney(b.remaining)} left`
          : `${formatMoney(b.spent)} of ${formatMoney(b.amount)} spent · ${formatMoney(Math.abs(b.remaining))} over budget`;
      return `
        <div class="budget-item">
          <div class="budget-item-header">
            <span class="category-dot" style="background:${color}"></span>
            <strong>${escapeHtml(b.category)}</strong>
            <span class="tag-pill">${b.period}</span>
            <button class="delete-btn" data-category="${encodeURIComponent(b.category)}" title="Remove budget">✕</button>
          </div>
          <div class="budget-bar"><div class="budget-bar-fill ${barClass}" style="width:${Math.min(100, b.pct)}%"></div></div>
          <div class="budget-item-meta">${metaText}</div>
        </div>
      `;
    })
    .join("");
}

function renderRecurring(items) {
  if (!items.length) {
    recurringList.innerHTML = "";
    recurringEmpty.style.display = "block";
    return;
  }
  recurringEmpty.style.display = "none";

  recurringList.innerHTML = items
    .map((r) => {
      const color = colorForCategory(r.category);
      const isPaused = !r.active;
      return `
        <div class="recurring-item ${isPaused ? "paused" : ""}">
          <span class="category-dot" style="background:${color}"></span>
          <div class="expense-info">
            <div class="expense-desc">${escapeHtml(r.description)}</div>
            <div class="expense-meta">${escapeHtml(r.category)} · ${r.frequency} · next ${r.next_date}</div>
          </div>
          <span class="tag-pill ${isPaused ? "paused" : ""}">${isPaused ? "Paused" : "Active"}</span>
          <div class="expense-amount">${formatMoney(r.amount)}</div>
          <div class="row-actions">
            <button class="edit-btn" data-id="${r.id}" data-active="${r.active}" title="${isPaused ? "Resume" : "Pause"}">${isPaused ? "▶" : "⏸"}</button>
            <button class="delete-btn" data-id="${r.id}" title="Delete">✕</button>
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadBudgets() {
  renderBudgets(await apiCall("/api/budgets"));
}

async function loadRecurring() {
  renderRecurring(await apiCall("/api/recurring"));
}

budgetForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiCall("/api/budgets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category: budgetCategory.value,
        amount: budgetAmount.value,
        period: budgetPeriod.value,
      }),
    });
    budgetCategory.value = "";
    budgetAmount.value = "";
    await loadBudgets();
    showToast("Budget saved", { type: "success" });
  } catch (err) {
    showError(err.message);
  }
});

budgetsList.addEventListener("click", async (e) => {
  const btn = e.target.closest(".delete-btn");
  if (!btn) return;
  try {
    await apiCall(`/api/budgets/${btn.dataset.category}`, { method: "DELETE" });
    await loadBudgets();
  } catch (err) {
    showError(err.message);
  }
});

recurringForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiCall("/api/recurring", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description: recurringDesc.value,
        amount: recurringAmount.value,
        category: recurringCategory.value,
        frequency: recurringFrequency.value,
        start_date: recurringStart.value || todayISO(),
      }),
    });
    recurringDesc.value = "";
    recurringAmount.value = "";
    recurringCategory.value = "";
    await loadRecurring();
    await loadCategoriesForSuggestions();
    showToast("Recurring item added", { type: "success" });
  } catch (err) {
    showError(err.message);
  }
});

recurringList.addEventListener("click", async (e) => {
  const editBtn = e.target.closest(".edit-btn");
  if (editBtn) {
    try {
      await apiCall(`/api/recurring/${editBtn.dataset.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: editBtn.dataset.active !== "1" }),
      });
      await loadRecurring();
    } catch (err) {
      showError(err.message);
    }
    return;
  }

  const deleteBtn = e.target.closest(".delete-btn");
  if (!deleteBtn) return;
  try {
    await apiCall(`/api/recurring/${deleteBtn.dataset.id}`, { method: "DELETE" });
    await loadRecurring();
  } catch (err) {
    showError(err.message);
  }
});

recurringStart.value = todayISO();

(async function init() {
  await loadCategoriesForSuggestions();
  await Promise.all([loadBudgets(), loadRecurring()]);
})();
