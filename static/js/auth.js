const mode = document.currentScript.dataset.mode;
const form = document.getElementById(mode === "signup" ? "signup-form" : "login-form");
const errorBanner = document.getElementById("auth-error");

function showAuthError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBanner.classList.remove("visible");

  const submitBtn = form.querySelector("button[type=submit]");
  submitBtn.disabled = true;

  const body = {
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
  };
  if (mode === "signup") {
    body.business_name = document.getElementById("business-name").value;
  }

  try {
    const res = await fetch(mode === "signup" ? "/signup" : "/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong");

    const params = new URLSearchParams(window.location.search);
    window.location.href = params.get("next") || "/";
  } catch (err) {
    showAuthError(err.message);
    submitBtn.disabled = false;
  }
});
