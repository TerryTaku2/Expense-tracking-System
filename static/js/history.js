const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");

function formatMoney(value) {
  return `$${Number(value).toFixed(2)}`;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

async function loadHistory() {
  const res = await fetch("/api/history");
  const days = await res.json();

  if (!days.length) {
    historyEmpty.style.display = "block";
    return;
  }

  historyList.innerHTML = days
    .map((day) => {
      const balanceClass = day.balance < 0 ? "negative" : "positive";
      return `
        <a class="history-row" href="/?date=${day.date}">
          <div class="history-date">${formatDate(day.date)}</div>
          <div class="history-metrics">
            <span>Start: <strong>${formatMoney(day.starting_balance)}</strong></span>
            <span>Spent: <strong>${formatMoney(day.total_spent)}</strong></span>
            <span>${day.expense_count} expense${day.expense_count === 1 ? "" : "s"}</span>
          </div>
          <div class="history-balance ${balanceClass}" style="color: ${day.balance < 0 ? "var(--danger)" : "var(--success)"};">
            ${formatMoney(day.balance)}
          </div>
        </a>
      `;
    })
    .join("");
}

loadHistory();
