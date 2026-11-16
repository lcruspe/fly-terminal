(() => {
  "use strict";
  const form = document.querySelector("#login-form");
  const button = form.querySelector("button");
  const status = form.querySelector(".status");
  const redirect = new URLSearchParams(location.search).get("next") || "/";
  const destination = redirect.startsWith("/") && !redirect.startsWith("//") && !redirect.includes("\\") ? redirect : "/";
  function base64(value) {
    const bytes = new TextEncoder().encode(value);
    let output = "";
    for (const byte of bytes) output += String.fromCharCode(byte);
    return btoa(output);
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const username = form.elements.username.value;
    const password = form.elements.password.value;
    status.textContent = "";
    button.disabled = true;
    try {
      const response = await fetch("/auth/issue", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { Authorization: "Basic " + base64(username + ":" + password) },
      });
      if (!response.ok) {
        status.textContent = response.status === 401 ? "Неверный логин или пароль либо нет доступа к этому сервису." : "Вход не выполнен. Повторите попытку.";
        return;
      }
      form.elements.password.value = "";
      location.replace(destination);
    } catch {
      status.textContent = "Нет соединения со шлюзом.";
    } finally {
      button.disabled = false;
    }
  });
})();
