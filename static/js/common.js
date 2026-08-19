const CATEGORY_COLORS = {
  Food: "#f59e0b",
  Transport: "#3b82f6",
  Bills: "#8b5cf6",
  Shopping: "#ec4899",
  Health: "#10b981",
  Entertainment: "#f43f5e",
  Other: "#6b7280",
};

// Any category not in the fixed palette above gets a stable color derived
// from its name, so custom user-entered categories still look consistent.
function colorForCategory(category) {
  if (CATEGORY_COLORS[category]) return CATEGORY_COLORS[category];
  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue}, 65%, 50%)`;
}

const THEME_KEY = "expense-tracker-theme";
const STREAK_KEY = "expense-tracker-last-streak";

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || "light";
  applyTheme(saved);
  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  }
}

const STREAK_MILESTONES = [3, 7, 14, 30, 60, 100, 200, 365];

// A day "counts" toward the streak if its balance stayed at or above zero.
// Streak = consecutive most-recent days (by date) that counted.
async function loadStreak({ celebrateOnIncrease = false } = {}) {
  const res = await fetch("/api/history");
  const days = await res.json();

  let streak = 0;
  for (const day of days) {
    if (day.balance >= 0) streak++;
    else break;
  }

  const countEl = document.getElementById("streak-count");
  const badge = document.getElementById("streak-badge");
  const flame = document.getElementById("streak-flame");
  if (countEl) countEl.textContent = streak;
  if (badge) badge.classList.toggle("streak-active", streak > 0);
  if (flame) flame.classList.toggle("streak-flame-lit", streak > 0);

  if (celebrateOnIncrease) {
    const previous = Number(localStorage.getItem(STREAK_KEY) || 0);
    if (streak > previous && STREAK_MILESTONES.includes(streak)) {
      fireConfetti();
      showToast(`🔥 ${streak}-day streak! You're on fire.`, { type: "success" });
    }
    localStorage.setItem(STREAK_KEY, String(streak));
  }

  return streak;
}

// opts.actionLabel + opts.onAction show a clickable button inside the toast
// (used for "Undo" after a delete) and keep it on screen a bit longer.
function showToast(message, opts = {}) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = "toast" + (opts.type ? ` toast-${opts.type}` : "");

  const text = document.createElement("span");
  text.textContent = message;
  toast.appendChild(text);

  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    toast.classList.remove("toast-visible");
    setTimeout(() => toast.remove(), 300);
  };

  if (opts.actionLabel && opts.onAction) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast-action";
    btn.textContent = opts.actionLabel;
    btn.addEventListener("click", () => {
      opts.onAction();
      dismiss();
    });
    toast.appendChild(btn);
  }

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-visible"));
  setTimeout(dismiss, opts.actionLabel ? 5000 : 2800);
}

function fireConfetti() {
  const canvas = document.createElement("canvas");
  canvas.className = "confetti-canvas";
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const colors = ["#4f46e5", "#f59e0b", "#10b981", "#ec4899", "#3b82f6", "#f43f5e"];

  const pieces = Array.from({ length: 90 }, () => ({
    x: canvas.width / 2 + (Math.random() - 0.5) * 240,
    y: canvas.height * 0.25,
    vx: (Math.random() - 0.5) * 9,
    vy: Math.random() * -9 - 4,
    size: Math.random() * 6 + 4,
    color: colors[Math.floor(Math.random() * colors.length)],
    rotation: Math.random() * 360,
    vr: (Math.random() - 0.5) * 12,
  }));

  let frame = 0;
  function tick() {
    frame++;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pieces.forEach((p) => {
      p.vy += 0.28;
      p.x += p.vx;
      p.y += p.vy;
      p.rotation += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate((p.rotation * Math.PI) / 180);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
      ctx.restore();
    });
    if (frame < 120) {
      requestAnimationFrame(tick);
    } else {
      canvas.remove();
    }
  }
  tick();
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {
      // Offline install support is a nice-to-have; failing silently keeps
      // the app usable even if registration is blocked (e.g. plain HTTP).
    });
  }
}

let deferredInstallPrompt = null;

// Chrome/Edge/Android support a native "install this app" flow triggered
// from a page button. iOS Safari has no such API — it only allows install
// via the Share sheet, so we surface a hint there instead of a real button.
function initInstallPrompt() {
  const btn = document.getElementById("install-btn");
  if (!btn) return;

  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  if (isStandalone) return;

  if (isIOS) {
    btn.textContent = "📲 Add to Home Screen";
    btn.style.display = "inline-flex";
    btn.addEventListener("click", () => {
      showToast('Tap the Share icon, then "Add to Home Screen"', { type: "success" });
    });
    return;
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    btn.style.display = "inline-flex";
  });

  btn.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    btn.style.display = "none";
    deferredInstallPrompt.prompt();
    const { outcome } = await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    if (outcome === "accepted") {
      showToast("Installed! 🎉", { type: "success" });
    }
  });

  window.addEventListener("appinstalled", () => {
    btn.style.display = "none";
  });
}

initTheme();
loadStreak();
registerServiceWorker();
initInstallPrompt();
