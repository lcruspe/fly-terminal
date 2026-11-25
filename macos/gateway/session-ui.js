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
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "session-menu-trigger";
    trigger.textContent = "Сессия ▾";
    trigger.setAttribute("popovertarget", "gatewaySessionMenu");
    const panel = document.createElement("div");
    panel.id = "gatewaySessionMenu";
    panel.className = "session-menu";
    panel.setAttribute("popover", "auto");
    panel.setAttribute("aria-label", "Действия сессии");
    const expiration = new Date(session.expires_at * 1000).toLocaleDateString("ru-RU", { day:"2-digit", month:"short" });
    const label = document.createElement("span");
    label.className = "session-expiration";
    label.textContent = "Вход до " + expiration;
    panel.append(label);
    const error = document.createElement("span");
    error.className = "session-error";
    error.setAttribute("role", "status");
    let busy = false;
    const buttons = [];
    function addAction(text, path, confirmation) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      if (confirmation) button.className = "session-revoke";
      button.addEventListener("click", async () => {
        if (busy || (confirmation && !confirm(confirmation))) return;
        busy = true;
        buttons.forEach(item => item.disabled = true);
        error.textContent = "";
        try { await action(path); }
        catch {
          busy = false;
          buttons.forEach(item => item.disabled = false);
          error.textContent = "Операция не выполнена";
        }
      });
      buttons.push(button);
      panel.append(button);
    }
    addAction("Выйти", "/auth/logout");
    if (session.is_admin) addAction("Отозвать все сессии", "/auth/revoke-all",
      "Отозвать все сессии на всех устройствах, включая текущую?");
    panel.append(error);
    function position() {
      if (!panel.matches(":popover-open")) return;
      const rect = trigger.getBoundingClientRect();
      const width = panel.offsetWidth, height = panel.offsetHeight;
      panel.style.left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)) + "px";
      panel.style.top = Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - height - 8)) + "px";
    }
    panel.addEventListener("toggle", position);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, { passive:true });
    host.append(trigger, panel);
  })().catch(() => {});
})();
