const txnBody = document.getElementById("txn-body");
const txnEmpty = document.getElementById("txn-empty");
const errorBanner = document.getElementById("error-banner");

function formatMoney(value) {
  return `$${Number(value).toFixed(2)}`;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
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

async function loadTransactions() {
  const res = await fetch("/api/transactions");
  const transactions = await res.json();

  if (!transactions.length) {
    txnEmpty.style.display = "block";
    txnBody.innerHTML = "";
    return;
  }
  txnEmpty.style.display = "none";

  txnBody.innerHTML = transactions
    .map((t) => {
      const color = colorForCategory(t.category);
      return `
        <tr data-id="${t.id}">
          <td>${formatDate(t.date)}</td>
          <td><span class="category-pill" style="background:${color}22; color:${color};">
            <span class="category-dot" style="background:${color};"></span>${escapeHtml(t.category)}
          </span></td>
          <td>${escapeHtml(t.description)}</td>
          <td class="txn-amount-col">-${formatMoney(t.amount)}</td>
          <td><button class="delete-btn" data-id="${t.id}" title="Delete">✕</button></td>
        </tr>
      `;
    })
    .join("");
}

txnBody.addEventListener("click", async (e) => {
  const btn = e.target.closest(".delete-btn");
  if (!btn) return;
  try {
    const res = await fetch(`/api/expenses/${btn.dataset.id}`, { method: "DELETE" });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Could not delete transaction");
    }
    await loadTransactions();
  } catch (err) {
    showError(err.message);
  }
});

loadTransactions();
