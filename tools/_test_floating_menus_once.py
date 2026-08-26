import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--window-size=1440,900")
driver = webdriver.Chrome(options=opts)
wait = WebDriverWait(driver, 12)

stub = r'''
(() => {
  const realFetch = window.fetch.bind(window);
  const ok = (payload) => Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: {'Content-Type':'application/json'}
  }));
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!url.includes('/api/')) return realFetch(input, init);
    if (url.includes('/api/ui/preferences')) return ok({ok:true});
    if (url.includes('/api/browser/config')) return ok({ok:true, enabled:false, url:''});
    if (url.includes('/api/desktop/config')) return ok({ok:true, enabled:false, url:'', rawUrl:''});
    if (url.includes('/api/apps/list')) return ok({ok:true, apps:[]});
    if (url.includes('/api/mac/apps/list')) return ok({ok:true, apps:[]});
    if (url.includes('/api/files/list')) return ok({ok:true, directory:'Documents', maxUploadBytes:26214400, files:[]});
    if (url.includes('/api/vpn/happ/subscriptions') || url.includes('/api/vpn/happ/locations')) return ok({ok:true, subscriptions:[], configured:false, current:'', currentSubscriptionId:'', currentLocationId:''});
    if (url.includes('/api/vpn/happ/status')) return ok({ok:true, state:'Disconnected', location:''});
    if (url.includes('/api/system/recover/status') || url.includes('/api/system/update/status')) return ok({ok:true, state:'idle', summary:'', entries:[]});
    if (url.includes('/api/sessions/list')) return ok({ok:true, sessions:[]});
    return ok({ok:true});
  };
})();
'''
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stub})
driver.get("http://127.0.0.1:8765/index.html")
wait.until(lambda d: d.find_element(By.ID, "settingsMenu"))
wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
time.sleep(0.8)

failures = []
results = []
PAD = 9


def close_all():
    driver.execute_script("document.querySelectorAll('details[open]').forEach(d => d.removeAttribute('open'))")
    time.sleep(0.05)


def check_menu(menu_id, orientation):
    close_all()
    driver.execute_script("applyToolbarOrientation(arguments[0]);", orientation)
    time.sleep(0.12)
    details = driver.find_element(By.ID, menu_id)
    summary = details.find_element(By.CSS_SELECTOR, ":scope > summary")
    driver.execute_script('arguments[0].scrollIntoView({block:"center", inline:"center"})', summary)
    summary.click()
    wait.until(lambda d: details.get_attribute("open") is not None)
    time.sleep(0.18)
    panel = details.find_element(By.CSS_SELECTOR, ":scope > summary + *")
    m = driver.execute_script(
        """
        const r = arguments[0].getBoundingClientRect();
        const cs = getComputedStyle(arguments[0]);
        return {left:r.left, top:r.top, right:r.right, bottom:r.bottom,
                width:r.width, height:r.height, vw:innerWidth, vh:innerHeight,
                display:cs.display, visibility:cs.visibility, position:cs.position};
        """,
        panel,
    )
    ok = (
        m["width"] > 0
        and m["height"] > 0
        and m["display"] != "none"
        and m["visibility"] != "hidden"
        and m["position"] == "fixed"
        and m["left"] >= PAD
        and m["top"] >= PAD
        and m["right"] <= m["vw"] - PAD
        and m["bottom"] <= m["vh"] - PAD
    )
    results.append({"menu": menu_id, "orientation": orientation, "ok": ok, "metrics": m})
    if not ok:
        failures.append(f"{menu_id}/{orientation}: {m}")


driver.set_window_size(1440, 900)
for orientation in ("horizontal", "vertical-left", "vertical-right"):
    check_menu("settingsMenu", orientation)
    check_menu("toolsMenu", orientation)

# Opening another top-level menu must leave only the new one open.
driver.set_window_size(1440, 900)
driver.execute_script("applyToolbarOrientation('horizontal');")
close_all()
settings = driver.find_element(By.ID, "settingsMenu")
tools = driver.find_element(By.ID, "toolsMenu")
settings.find_element(By.CSS_SELECTOR, ":scope > summary").click()
time.sleep(0.08)
tools.find_element(By.CSS_SELECTOR, ":scope > summary").click()
time.sleep(0.1)
exclusivity = settings.get_attribute("open") is None and tools.get_attribute("open") is not None
results.append({"behavior": "exclusivity", "ok": exclusivity})
if not exclusivity:
    failures.append("opening Tools did not close Settings")

# Outside pointerdown closes the active floating menu.
driver.execute_script("document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));")
time.sleep(0.1)
outside_closed = tools.get_attribute("open") is None
results.append({"behavior": "outside-click", "ok": outside_closed})
if not outside_closed:
    failures.append("outside pointerdown did not close Tools")

# Escape closes a floating menu without requiring focus inside it.
settings.find_element(By.CSS_SELECTOR, ":scope > summary").click()
time.sleep(0.08)
driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
time.sleep(0.1)
escape_closed = settings.get_attribute("open") is None
results.append({"behavior": "escape", "ok": escape_closed})
if not escape_closed:
    failures.append("Escape did not close Settings")

# Pointerdown inside the open panel must not dismiss it.
settings.find_element(By.CSS_SELECTOR, ":scope > summary").click()
time.sleep(0.08)
panel = settings.find_element(By.CSS_SELECTOR, ":scope > summary + *")
driver.execute_script("arguments[0].dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));", panel)
time.sleep(0.08)
inside_kept = settings.get_attribute("open") is not None
results.append({"behavior": "inside-click", "ok": inside_kept})
if not inside_kept:
    failures.append("inside pointerdown unexpectedly closed Settings")

print("FLOATING_MENU_RESULTS=" + json.dumps(results, ensure_ascii=False))
driver.quit()

if failures:
    print("FLOATING_MENU_FAILURES=" + json.dumps(failures, ensure_ascii=False))
    raise SystemExit(1)
