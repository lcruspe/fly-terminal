(() => {
  "use strict";
  const host = window.location.hostname;
  const local = ["127.0.0.1", "localhost", "[::1]"].includes(host);
  // The Linux Tailscale gateway forwards the macOS Caddy ports as plain TCP.
  // The historic public Funnel links (HTTPS 8443/10000) must remain unchanged.
  const linuxGateway = host === "100.125.224.119" || host === "mac-gateway" || host === "mac-gateway.tail1c55c5.ts.net";
  // HTTPS is required for RoomAudio / YT Transcriber session cookies.
  // Keep Linux-gateway public links on the Tailscale HTTPS Serve endpoints.
  const secureGateway = linuxGateway && window.location.protocol === "https:";
  const directPortAccess = local || (linuxGateway && !secureGateway) || (window.location.protocol === "http:" && window.location.port === "8080");
  const localPorts = { "8443": "8081", "10000": "8082" };
  document.querySelectorAll("[data-port]").forEach((link) => {
    const port = link.dataset.port;
    const path = link.dataset.path || "/";
    link.href = `${directPortAccess ? "http" : "https"}://${host}:${directPortAccess ? (localPorts[port] || port) : port}${path}`;
  });
  // LuCI has a private LAN address. Reach it through a tailnet-only TCP forwarder.
  if (linuxGateway) {
    document.querySelectorAll('a[href^="http://192.168.1.115/"]').forEach((link) => {
      const target = new URL(link.href);
      link.href = `${secureGateway ? "https" : "http"}://${host}:${secureGateway ? "10443" : "8115"}${target.pathname}${target.search}${target.hash}`;
    });
  }
  const dashboard = document.querySelector("[data-dashboard]");
  if (!dashboard) return; // The restricted Sprut.Hub page has no admin controls.
  const message = dashboard.querySelector(".catalog-message");
  const storageKey = "fly-gateway-view-v1";
  const detailsKey = "fly-gateway-actions-v1";
  const modes = ["tiles", "compact", "table"];
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };
  let tableContainer, tableMoves = [];
  function renderTable(active) {
    const services = dashboard.querySelector(".services");
    if (!services) return;
    if (active && !tableContainer) {
      tableContainer = document.createElement("div");
      tableContainer.className = "service-table-scroll";
      tableContainer.tabIndex = 0;
      tableContainer.setAttribute("role", "region");
      tableContainer.setAttribute("aria-label", "Таблица сервисов — горизонтальная прокрутка");
      const table = document.createElement("table");
      table.className = "service-table";
      const caption = table.createCaption();
      caption.textContent = "Каталог сервисов";
      const head = table.createTHead().insertRow();
      ["Сервис", "Состояние", "Описание", "Действия"].forEach(label => {
        const cell = document.createElement("th");
        cell.scope = "col";
        cell.textContent = label;
        head.append(cell);
      });
      const body = table.createTBody();
      services.querySelectorAll(".service").forEach(card => {
        const row = body.insertRow();
        row.dataset.service = card.dataset.service;
        const name = document.createElement("th");
        name.scope = "row";
        row.append(name);
        const status = row.insertCell(), description = row.insertCell(), actions = row.insertCell();
        const move = (node, cell) => {
          if (!node) return;
          const marker = document.createComment("card position");
          node.before(marker);
          tableMoves.push({node, marker, cell});
        };
        move(card.querySelector(".service-main"), name);
        // Move the existing nodes; preserve listeners, open details and live statuses.
        card.querySelectorAll(".service-heading > [data-health], .roomaudio-status, .variant-status, .router-status").forEach(node => move(node, status));
        move(card.querySelector(".service-description"), description);
        move(card.querySelector("details"), actions);
      });
      tableContainer.append(table);
      services.after(tableContainer);
    }
    if (tableContainer) {
      tableMoves.forEach(({node, marker, cell}) => active ? cell.append(node) : marker.after(node));
      tableContainer.hidden = !active;
    }
    services.hidden = active;
  }
  function setView(mode) {
    if (mode === "list") mode = "table"; // Migrate the saved list preference.
    dashboard.dataset.view = modes.includes(mode) ? mode : "tiles";
    renderTable(dashboard.dataset.view === "table");
    dashboard.querySelectorAll("[data-view-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.viewMode === dashboard.dataset.view)));
  }
  setView(read(storageKey, window.matchMedia("(max-width: 600px)").matches ? "compact" : "tiles"));
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
    dot.setAttribute("aria-label", `${dot.parentElement.textContent.trim() || key}: ${text}`);
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
