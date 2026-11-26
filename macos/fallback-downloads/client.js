(() => {
  const key = 'fly-fallback-download-mode';
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  let enabled = localStorage.getItem(key) !== 'colima', claim = true, busy = false;
  const seen = new Set();
  const retry = document.createElement('div');
  retry.style.cssText = 'position:fixed;right:12px;bottom:47px;z-index:2147483647;max-width:min(320px,90vw);display:none;background:#20242b;color:white;padding:8px;border-radius:9px;font:12px system-ui;overflow-wrap:anywhere';
  function downloadLink(d) {
    const a = document.createElement('a');
    a.href = './fly-downloads/file/' + encodeURIComponent(d.token);
    a.download = d.name;
    return a;
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;border:1px solid #667085;border-radius:9px;background:#20242b;color:#fff;padding:7px 11px;font:12px system-ui;cursor:pointer;opacity:.88';
  function render(ready = true) {
    button.textContent = !ready ? '⇩ Недоступно' : enabled ? '⇩ Клиент' : '⇩ Colima';
    button.title = 'Место сохранения загрузок: нажмите для переключения';
    button.setAttribute('aria-label', button.title);
  }
  function poll() {
    if (busy) return;
    busy = true;
    const wantsClaim = claim;
    claim = false;
    fetch('./fly-downloads/poll', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, cache: 'no-store',
      body: JSON.stringify({client:id, enabled, active:!document.hidden && document.hasFocus(), claim:wantsClaim})
    }).then(r => {if (!r.ok) throw Error(); return r.json();}).then(data => {
      render(data.ready);
      if (!data.ready) return;
      retry.replaceChildren();
      const pending = data.downloads.filter(d => !d.active && seen.has(d.id) && d.state === 'completed');
      if (pending.length) {
        retry.style.display = 'block';
        for (const d of pending) {
          const a = downloadLink(d);
          a.style.cssText = 'display:block;color:#a7d8ff;padding:4px';
          a.textContent = 'Скачать: ' + d.name;
          retry.append(a);
        }
      } else retry.style.display = 'none';
      for (const d of data.downloads) {
        if (!seen.has(d.id) && !d.active) {
          seen.add(d.id);
          const a = downloadLink(d);
          document.body.append(a);
          a.click();
          a.remove();
        }
      }
    }).catch(() => {claim = claim || wantsClaim; render(false);}).finally(() => {busy = false;});
  }
  button.addEventListener('click', e => {
    e.stopPropagation();
    enabled = !enabled;
    localStorage.setItem(key, enabled ? 'client' : 'colima');
    claim = true;
    render();
    poll();
  });
  for (const type of ['pointerdown','keydown','focus']) window.addEventListener(type, () => {claim = true; poll();}, true);
  window.addEventListener('storage', e => {if (e.key === key) {enabled = e.newValue !== 'colima';poll();}});
  document.addEventListener('visibilitychange', () => {if (!document.hidden) {claim = true;poll();}});
  function start() {document.body.append(retry,button);render(false);poll();setInterval(poll, 800);}
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true}); else start();
})();
