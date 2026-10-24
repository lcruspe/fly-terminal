(() => {
  "use strict";
  document.querySelectorAll("[data-port]").forEach((link) => {
    const port = link.dataset.port;
    const path = link.dataset.path || "/";
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname);
    const localPorts = { "8443": "8081", "10000": "8082" };
    link.href = `${local ? "http" : "https"}://${window.location.hostname}:${local ? (localPorts[port] || port) : port}${path}`;
  });
  const dashboard = document.querySelector("[data-dashboard]");
  if (!dashboard) return; // The restricted Sprut.Hub page has no admin controls.
  const message = dashboard.querySelector(".catalog-message");
  const storageKey = "fly-gateway-view-v1";
  const detailsKey = "fly-gateway-actions-v1";
  const modes = ["tiles", "compact", "list"];
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };
  function setView(mode) {
    dashboard.dataset.view = modes.includes(mode) ? mode : "tiles";
    dashboard.querySelectorAll("[data-view-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.viewMode === dashboard.dataset.view)));
  }
  setView(read(storageKey, "tiles"));
  dashboard.querySelectorAll("[data-view-mode]").forEach(button => button.addEventListener("click", () => {
    setView(button.dataset.viewMode);
    write(storageKey, dashboard.dataset.view);
  }));
  let opened = read(detailsKey, {});
  if (!opened || typeof opened !== "object" || Array.isArray(opened)) opened = {};
  dashboard.querySelectorAll("details[data-details-key]").forEach(details => {
    details.open = opened[details.dataset.detailsKey] === true;
    details.addEventListener("toggle", () => {
      opened[details.dataset.detailsKey] = details.open;
      write(detailsKey, opened);
    });
  });

  let csrf = "", pending = false;
  const labels = { start: "Запустить", stop: "Остановить", restart: "Перезапустить", "vpn-connect": "Подключить VPN", "vpn-disconnect": "Отключить VPN" };
  const names = { native: "браузер Native", fallback: "браузер Fallback", roomaudio: "сервер RoomAudio", yt: "YT Transcript", spruthub: "подключение к Sprut.Hub", openwrt: "Amnezia VPN" };
  const indicators = new Map();
  dashboard.querySelectorAll("[data-health]").forEach(node => {
    const dot = document.createElement("span");
    dot.className = "service-health";
    dot.setAttribute("role", "status");
    node.append(dot);
    indicators.set(node.dataset.health, dot);
  });
  function indicator(key, state) {
    const dot = indicators.get(key);
    if (!dot) return;
    dot.dataset.state = state;
    const text = { up: "Доступен", down: "Недоступен", unknown: "Нет данных" }[state] || "Проверка";
    dot.title = text;
    dot.setAttribute("aria-label", text);
  }
  indicators.forEach((_, key) => indicator(key, "checking"));
  const controls = [];
  dashboard.querySelectorAll("[data-controls]").forEach(container => {
    const service = container.dataset.controls;
    const actions = service === "openwrt" ? ["vpn-connect", "vpn-disconnect"] : ["start", "stop", "restart"];
    actions.forEach(action => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labels[action];
      button.dataset.service = service;
      button.dataset.action = action;
      button.disabled = true;
      button.addEventListener("click", () => act(service, action));
      container.append(button);
      controls.push(button);
    });
  });
  let supported = {};
  function enableControls() {
    controls.forEach(button => {
      button.disabled = pending || !csrf || !(supported[button.dataset.service] || []).includes(button.dataset.action);
    });
  }
  async function request(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Сервис управления недоступен.");
    return data;
  }
  async function refresh() {
    const data = await request("/gateway-control/status", { signal: AbortSignal.timeout(15000) });
    csrf = data.csrf;
    supported = data.actions || {};
    indicators.forEach((_, key) => indicator(key, key === "openwrt" ? (data.openwrt.reachable ? "up" : "down") : data.services[key] || "unknown"));
    dashboard.querySelector(".router-status").textContent = data.openwrt.reachable
      ? (data.openwrt.connected ? `VPN: ${data.openwrt.location}` : "VPN отключён · интернет напрямую") : "Нет связи с роутером";
    enableControls();
  }
  async function act(service, action) {
    if (pending) return;
    const risky = ["stop", "restart", "vpn-disconnect"].includes(action);
    if (risky && !window.confirm(`${labels[action]}: ${names[service]}? Активные подключения этого сервиса будут прерваны.`)) return;
    pending = true;
    enableControls();
    message.textContent = `${labels[action]}: ${names[service]}…`;
    message.dataset.error = "false";
    try {
      const data = await request("/gateway-control/action", {
        method: "POST", signal: AbortSignal.timeout(90000),
        headers: { "Content-Type": "application/json", "X-Gateway-CSRF": csrf },
        body: JSON.stringify({ service, action, confirmed: risky })
      });
      message.textContent = data.message;
      await refresh();
    } catch (error) {
      message.textContent = error.name === "TimeoutError" ? "Время ожидания истекло. Проверьте состояние перед повторной командой." : error.message;
      message.dataset.error = "true";
      try { await refresh(); } catch {}
    } finally {
      pending = false;
      enableControls();
    }
  }
  async function poll() {
    if (pending) return;
    try {
      await refresh();
      if (message.textContent === "Управление недоступно. Ссылки на сервисы продолжают работать.") message.textContent = "";
    }
    catch {
      csrf = "";
      enableControls();
      indicators.forEach((_, key) => indicator(key, "unknown"));
      if (!message.textContent) message.textContent = "Управление недоступно. Ссылки на сервисы продолжают работать.";
    }
  }
  poll();
  setInterval(poll, 15000);
})();
