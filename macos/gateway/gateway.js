document.querySelectorAll("[data-port]").forEach((link) => {
  const port = link.dataset.port;
  const path = link.dataset.path || "/";
  link.href = `https://${window.location.hostname}:${port}${path}`;
});
