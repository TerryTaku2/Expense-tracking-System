const txnBody = document.getElementById("txn-body");
const txnEmpty = document.getElementById("txn-empty");
const errorBanner = document.getElementById("error-banner");

const filterQ = document.getElementById("filter-q");
const filterCategory = document.getElementById("filter-category");
const filterDateFrom = document.getElementById("filter-date-from");
const filterDateTo = document.getElementById("filter-date-to");
const filterMin = document.getElementById("filter-min");
const filterMax = document.getElementById("filter-max");
const filterClearBtn = document.getElementById("filter-clear-btn");

const editModalBackdrop = document.getElementById("edit-modal-backdrop");
const editForm = document.getElementById("edit-form");
const editExpenseId = document.getElementById("edit-expense-id");
const editDesc = document.getElementById("edit-desc");
const editAmount = document.getElementById("edit-amount");
const editCategory = document.getElementById("edit-category");
const editCancelBtn = document.getElementById("edit-cancel-btn");

const restoreBtn = document.getElementById("restore-btn");
const restoreFileInput = document.getElementById("restore-file-input");

let currentTransactions = [];
let filterDebounce = null;

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

function clearError() {
  errorBanner.classList.remove("visible");
}

async function loadCategoriesForFilter() {
  try {
    const categories = await apiCall("/api/categories");
    document.getElementById("category-suggestions").innerHTML = categories.map((c) => `<option value="${c}"></option>`).join("");
  } catch (err) {
    showError(err.message);
  }
}

function buildQuery() {
  const params = new URLSearchParams();
  if (filterQ.value.trim()) params.set("q", filterQ.value.trim());
  if (filterCategory.value.trim()) params.set("category", filterCategory.value.trim());
  if (filterDateFrom.value) params.set("date_from", filterDateFrom.value);
  if (filterDateTo.value) params.set("date_to", filterDateTo.value);
  if (filterMin.value) params.set("min_amount", filterMin.value);
  if (filterMax.value) params.set("max_amount", filterMax.value);
  return params.toString();
}

async function loadTransactions() {
  let transactions;
  try {
    const query = buildQuery();
    transactions = await apiCall(`/api/transactions${query ? `?${query}` : ""}`);
    clearError();
  } catch (err) {
    showError(err.message);
    return;
  }
  currentTransactions = transactions;

  if (!transactions.length) {
    txnEmpty.style.display = "block";
    txnBody.innerHTML = "";
    return;
  }
  txnEmpty.style.display = "none";

  txnBody.innerHTML = transactions
    .map((t) => {
      const color = colorForCategory(t.category);
      const receiptLink = t.receipt_filename
        ? ` <a class="receipt-link" href="/receipts/${t.id}/${encodeURIComponent(t.receipt_filename)}" target="_blank" rel="noopener" title="View receipt"><svg class="icon"><use href="#icon-attach"/></svg></a>`
        : "";
      return `
        <tr data-id="${t.id}">
          <td>${formatDate(t.date)}</td>
          <td><span class="category-pill" style="background:${color}22; color:${color};">
            ${categoryDot(t.category, "small")}${escapeHtml(t.category)}
          </span></td>
          <td>${escapeHtml(t.description)}${receiptLink}</td>
          <td class="txn-amount-col">-${formatMoney(t.amount)}</td>
          <td>
            <div class="row-actions" style="justify-content:flex-end;">
              <button class="edit-btn" data-id="${t.id}" title="Edit"><svg class="icon"><use href="#icon-edit"/></svg></button>
              <button class="delete-btn" data-id="${t.id}" title="Delete"><svg class="icon"><use href="#icon-delete"/></svg></button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

[filterCategory, filterDateFrom, filterDateTo, filterMin, filterMax].forEach((el) => {
  el.addEventListener("change", loadTransactions);
});
filterQ.addEventListener("input", () => {
  clearTimeout(filterDebounce);
  filterDebounce = setTimeout(loadTransactions, 300);
});
filterClearBtn.addEventListener("click", () => {
  filterQ.value = "";
  filterCategory.value = "";
  filterDateFrom.value = "";
  filterDateTo.value = "";
  filterMin.value = "";
  filterMax.value = "";
  loadTransactions();
});

function openEditModal(expenseId) {
  const expense = currentTransactions.find((x) => x.id === expenseId);
  if (!expense) return;
  editExpenseId.value = expense.id;
  editDesc.value = expense.description;
  editAmount.value = expense.amount;
  editCategory.value = expense.category;
  editModalBackdrop.style.display = "flex";
}

function closeEditModal() {
  editModalBackdrop.style.display = "none";
}

editCancelBtn.addEventListener("click", closeEditModal);
editModalBackdrop.addEventListener("click", (e) => {
  if (e.target === editModalBackdrop) closeEditModal();
});

editForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiCall(`/api/expenses/${editExpenseId.value}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description: editDesc.value,
        amount: editAmount.value,
        category: editCategory.value,
      }),
    });
    closeEditModal();
    await loadTransactions();
    showToast("Expense updated");
  } catch (err) {
    showError(err.message);
  }
});

txnBody.addEventListener("click", async (e) => {
  const editBtn = e.target.closest(".edit-btn");
  if (editBtn) {
    openEditModal(Number(editBtn.dataset.id));
    return;
  }

  const deleteBtn = e.target.closest(".delete-btn");
  if (!deleteBtn) return;
  const id = deleteBtn.dataset.id;
  try {
    await apiCall(`/api/expenses/${id}`, { method: "DELETE" });
    await loadTransactions();
    showToast("Expense deleted", {
      actionLabel: "Undo",
      onAction: async () => {
        try {
          await apiCall(`/api/expenses/${id}/restore`, { method: "POST" });
          await loadTransactions();
          showToast("Restored");
        } catch (err) {
          showError(err.message);
        }
      },
    });
  } catch (err) {
    showError(err.message);
  }
});

restoreBtn.addEventListener("click", () => restoreFileInput.click());

restoreFileInput.addEventListener("change", async () => {
  const file = restoreFileInput.files[0];
  if (!file) return;
  const confirmed = confirm(
    "This will REPLACE all current data (days, expenses, income, budgets, recurring items) with the contents of this backup file. This cannot be undone. Continue?"
  );
  if (!confirmed) {
    restoreFileInput.value = "";
    return;
  }

  const formData = new FormData();
  formData.append("backup", file);
  try {
    await apiCall("/api/restore", { method: "POST", body: formData });
    showToast("Data restored ✅", { type: "success" });
    await loadTransactions();
  } catch (err) {
    showError(err.message);
  } finally {
    restoreFileInput.value = "";
  }
});

loadCategoriesForFilter();
loadTransactions();
