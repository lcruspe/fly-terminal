(() => {
  "use strict";
  const host = document.querySelector("[data-session-actions]");
  if (!host) return;
  async function action(path) {
    const response = await fetch(path, { method:"POST", credentials:"same-origin" });
    if (!response.ok) throw new Error("Операция не выполнена");
    location.replace("/auth/login");
  }
  (async () => {
    const response = await fetch("/auth/session", { credentials:"same-origin", cache:"no-store" });
    if (!response.ok) return;
    const session = await response.json();
    if (!session.ok) return;
    const expiration = new Date(session.expires_at * 1000).toLocaleDateString("ru-RU", { day:"2-digit", month:"short" });
    const label = document.createElement("span");
    label.textContent = "Вход до " + expiration;
    host.append(label);
    const logout = document.createElement("button");
    logout.textContent = "Выйти";
    logout.addEventListener("click", async () => {
      logout.disabled = true;
      try { await action("/auth/logout"); }
      catch { logout.disabled = false; }
    });
    host.append(logout);
    if (session.is_admin) {
      const revoke = document.createElement("button");
      revoke.textContent = "Отозвать все сессии";
      revoke.title = "Завершить все активные сессии на всех устройствах";
      revoke.addEventListener("click", async () => {
        if (!confirm("Отозвать все сессии на всех устройствах, включая текущую?")) return;
        revoke.disabled = true;
        try { await action("/auth/revoke-all"); }
        catch { revoke.disabled = false; }
      });
      host.append(revoke);
    }
  })().catch(() => {});
})();
