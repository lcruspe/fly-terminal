document.querySelectorAll("[data-port]").forEach((link) => {
  const port = link.dataset.port;
  const path = link.dataset.path || "/";
  link.href = `https://${window.location.hostname}:${port}${path}`;
});

(() => {
  const byLabel = {
    "Fly Terminal": "terminal",
    "Browser Native": "native",
    "Browser Fallback": "fallback",
    "RoomAudio": "roomaudio",
    "YT Transcript": "yt",
    "Sprut.Hub": "spruthub"
  };
  const indicators = new Map();
  const labels = { checking: "Проверка доступности", up: "Доступен", down: "Недоступен", unknown: "Проверка не удалась" };
  const updateIndicator = (indicator, state) => {
    const status = Object.hasOwn(labels, state) ? state : "unknown";
    indicator.dataset.state = status;
    indicator.title = labels[status];
    indicator.setAttribute("aria-label", labels[status]);
  };

  document.querySelectorAll(".service").forEach((link) => {
    const key = link.dataset.health || byLabel[link.querySelector("strong")?.textContent?.trim()];
    if (!key) return;
    const indicator = document.createElement("span");
    indicator.className = "service-health";
    indicator.setAttribute("role", "status");
    updateIndicator(indicator, "checking");
    link.append(indicator);
    indicators.set(key, indicator);
  });
  if (!indicators.size) return;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);
  fetch("/gateway-status", { credentials: "same-origin", cache: "no-store", signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) throw new Error("status request failed");
      const result = await response.json();
      if (!result.ok || !result.services) throw new Error("invalid status response");
      indicators.forEach((indicator, key) => updateIndicator(indicator, result.services[key] || "unknown"));
    })
    .catch(() => indicators.forEach((indicator) => updateIndicator(indicator, "unknown")))
    .finally(() => clearTimeout(timeout));
})();
