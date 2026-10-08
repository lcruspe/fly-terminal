(function () {
  function createDisplayAutoResize({ element, target, enabled, isConnected, onApplied, onError }) {
    let active = enabled;
    let lastApplied = "";
    let timer = null;
    let pending = false;
    let running = false;

    async function apply() {
      timer = null;
      if (!active || !isConnected() || document.visibilityState === "hidden") return;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const width = Math.max(100, Math.min(7680, Math.round(rect.width)));
      const height = Math.max(100, Math.min(4320, Math.round(rect.height)));
      const resolution = `${width}x${height}`;
      if (resolution === lastApplied) return;
      if (running) {
        pending = true;
        return;
      }
      running = true;
      try {
        const response = await fetch("/api/desktop/display-resolution", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target, resolution, automatic: true })
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
        lastApplied = resolution;
        onApplied(result.resolution);
      } catch (error) {
        onError(error);
      } finally {
        running = false;
        if (pending) {
          pending = false;
          schedule();
        }
      }
    }

    function schedule() {
      clearTimeout(timer);
      if (active) timer = setTimeout(apply, 450);
    }

    const observer = new ResizeObserver(schedule);
    observer.observe(element);
    window.addEventListener("resize", schedule, { passive: true });
    document.addEventListener("visibilitychange", schedule);

    return {
      schedule,
      setEnabled(value) {
        active = value === true;
        if (active) { lastApplied = ""; schedule(); }
        else clearTimeout(timer);
      }
    };
  }

  window.FlyDisplayAutoResize = createDisplayAutoResize;
})();
