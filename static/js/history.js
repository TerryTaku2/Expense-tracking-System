const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");
const errorBanner = document.getElementById("error-banner");

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

async function loadHistory() {
  let days;
  try {
    days = await apiCall("/api/history");
  } catch (err) {
    showError(err.message);
    return;
  }

  if (!days.length) {
    historyEmpty.style.display = "block";
    historyList.innerHTML = "";
    return;
  }
  historyEmpty.style.display = "none";

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
