from pathlib import Path
import re

SESSION = Path("session-control.py")
INDEX = Path("index.html")
TOOLS = Path("TOOLS.md")


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    return text.replace(old, new, 1)


text = SESSION.read_text(encoding="utf-8")

text = replace_once(
    text,
    '    "happ_location_switch_failed": "Не удалось переключить локацию Happ.",\n',
    '    "happ_location_switch_failed": "Не удалось переключить локацию Happ.",\n'
    '    "happ_routing_apply_failed": "Не удалось применить профиль маршрутизации Happ для выбранной подписки.",\n'
    '    "happ_routing_fallback_failed": "Happ не смог подключиться даже после отключения проблемного профиля маршрутизации.",\n',
    "Happ error messages",
)

helpers = r'''

def _normalize_happ_routing_deeplink(value):
    """Return only supported Happ routing deeplinks; never expose arbitrary cached URLs."""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    deeplink = str(value or "").strip()
    if not deeplink or len(deeplink) > 32768:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in deeplink):
        return ""
    lowered = deeplink.casefold()
    if lowered == "happ://routing/off":
        return "happ://routing/off"
    if lowered.startswith("happ://routing/onadd/") or lowered.startswith("happ://routing/add/"):
        return deeplink
    return ""


def _happ_subscription_routing_deeplink(response_object):
    """Extract the routing command that Happ itself received with a cached subscription."""
    archive = _resolve_plist_archive(response_object)
    routing = _normalize_happ_routing_deeplink(_find_named_value(archive, {"routing"}))
    if routing:
        return routing

    enabled = _find_named_value(archive, {"routing-enable", "routingenable"})
    if isinstance(enabled, (bytes, bytearray)):
        try:
            enabled = bytes(enabled).decode("utf-8")
        except UnicodeDecodeError:
            enabled = ""
    if str(enabled or "").strip().casefold() in {"0", "false", "off", "no"}:
        return "happ://routing/off"
    return ""
'''

marker = "\n\ndef _happ_locations_from_configs(configs):\n"
if "def _normalize_happ_routing_deeplink" not in text:
    text = replace_once(text, marker, helpers + marker, "routing metadata helpers")

text = replace_once(
    text,
    '                    "label": _happ_subscription_title(response_object, request_key),\n                    "locations": locations,\n',
    '                    "label": _happ_subscription_title(response_object, request_key),\n'
    '                    "routingDeeplink": _happ_subscription_routing_deeplink(response_object),\n'
    '                    "locations": locations,\n',
    "subscription routing metadata",
)

new_apply = r'''def _write_happ_current_config(location):
    config_json = json.dumps(location["config"], ensure_ascii=False, separators=(",", ":"))
    result = subprocess.run(
        ["plutil", "-replace", "connectedConfigJson", "-string", config_json, str(HAPP_PREFERENCES)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def run_happ_routing_deeplink(deeplink):
    deeplink = _normalize_happ_routing_deeplink(deeplink)
    if not deeplink:
        return False, "unsupported_happ_routing_deeplink"
    try:
        result = subprocess.run(
            ["/usr/bin/open", "-g", deeplink],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    # Happ processes routing deeplinks asynchronously. Give it a short window to
    # persist/activate the profile before the network extension is restarted.
    time.sleep(1.0)
    return True, ""


def restart_happ_vpn():
    state, state_error = happ_vpn_status()
    if state == "Unavailable":
        return False, state_error or "happ_service_unavailable"

    if state != "Disconnected":
        stopped, stop_error = run_happ_vpn_command("stop")
        if not stopped:
            return False, stop_error or "happ_disconnect_failed"
        stopped_state, stopped_error = wait_for_happ_vpn({"Disconnected"}, 10)
        if stopped_state != "Disconnected":
            return False, stopped_error or f"Happ stayed in {stopped_state} while stopping"

    started, start_error = run_happ_vpn_command("start")
    if not started:
        return False, start_error or "happ_connect_failed"
    connected_state, connected_error = wait_for_happ_vpn({"Connected"}, 20)
    if connected_state != "Connected":
        return False, connected_error or f"Happ stayed in {connected_state} while starting"
    return True, ""


def apply_happ_location(subscription, location):
    """Apply server + subscription routing, with a one-shot no-routing recovery.

    Happ can reject a routing profile when its GeoIP/GeoSite data is stale or
    incompatible (for example, a profile references geoip:RU but the active
    geoip.dat has no RU section). We first ask Happ to apply its own routing
    deeplink, so its normal geofile manager gets a chance to repair/update the
    profile. If the tunnel still cannot start, we retry once with the official
    happ://routing/off command — the same semantic fallback as Happ's manual
    "Запуск" action, but without GUI automation.
    """
    written, write_error = _write_happ_current_config(location)
    if not written:
        return False, write_error, False

    routing_deeplink = ""
    if isinstance(subscription, dict):
        routing_deeplink = _normalize_happ_routing_deeplink(subscription.get("routingDeeplink"))

    routing_profile_active = bool(routing_deeplink and routing_deeplink != "happ://routing/off")
    if routing_deeplink:
        routing_ok, routing_error = run_happ_routing_deeplink(routing_deeplink)
        if not routing_ok:
            return False, routing_error or "happ_routing_apply_failed", False

    connected, connect_error = restart_happ_vpn()
    if connected and happ_current_location() == location["label"]:
        return True, "", False

    # A failed Xray routing profile surfaces in Happ as a blocking dialog. Do
    # not automate that dialog. Disable routing through Happ's documented
    # deeplink and restart the tunnel once instead.
    if routing_profile_active:
        fallback_ok, fallback_error = run_happ_routing_deeplink("happ://routing/off")
        if fallback_ok:
            connected, retry_error = restart_happ_vpn()
            if connected and happ_current_location() == location["label"]:
                return True, "", True
            connect_error = retry_error or connect_error
        else:
            connect_error = fallback_error or connect_error

    return False, connect_error or "happ_location_switch_failed", False


def happ_vpn_status():'''

pattern = re.compile(r"def apply_happ_location\(location\):.*?\n\ndef happ_vpn_status\(\):", re.S)
if not pattern.search(text):
    raise SystemExit("apply_happ_location block not found")
text = pattern.sub(new_apply, text, count=1)

text = replace_once(
    text,
    "            switched, switch_error = apply_happ_location(location)\n            final_state, final_error = happ_vpn_status()\n",
    "            switched, switch_error, routing_fallback = apply_happ_location(subscription or {}, location)\n            final_state, final_error = happ_vpn_status()\n",
    "location handler apply call",
)

text = replace_once(
    text,
    '                "subscription": subscription["label"] if subscription else "",\n                "location": happ_current_location() or location["label"],\n',
    '                "subscription": subscription["label"] if subscription else "",\n'
    '                "location": happ_current_location() or location["label"],\n'
    '                "routingFallback": routing_fallback,\n',
    "location handler response",
)

SESSION.write_text(text, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")
html = replace_once(
    html,
    '''        renderHappState(payload);\n        setStatusText(`Happ: ${payload.subscription || subscriptionLabel} → ${payload.location || selectedLabel}`, 2800);''',
    '''        renderHappState(payload);\n        if (payload.routingFallback) {\n          setHappStatus("warn", "Подключено без маршрутизации: профиль Happ не запустился с текущими GeoIP/GeoSite");\n          setStatusText(`Happ: ${payload.subscription || subscriptionLabel} → ${payload.location || selectedLabel} · без маршрутизации`, 5200);\n        } else {\n          setStatusText(`Happ: ${payload.subscription || subscriptionLabel} → ${payload.location || selectedLabel}`, 2800);\n        }''',
    "frontend routing fallback status",
)
INDEX.write_text(html, encoding="utf-8")

docs = TOOLS.read_text(encoding="utf-8")
doc_marker = "Если `Cache.db` отсутствует или недоступен, остаётся fallback на прямое чтение `fsCachedData`. В этом режиме локации продолжают работать, но название подписки может быть обобщённым.\n"
doc_addition = '''\n### Маршрутизация подписки и восстановление Xray\n\nПри переключении подписки backend также извлекает из её закэшированных HTTP-метаданных служебный параметр `routing` / `routing-enable`. Если подписка передала официальный deeplink `happ://routing/...`, Fly Terminal применяет его через macOS `open -g` перед перезапуском VPN. Сам deeplink остаётся только на backend и никогда не возвращается через публичный API. Это важно: смена подписки теперь синхронизирует не только `connectedConfigJson`, но и связанный с подпиской routing-профиль Happ.\n\nЕсли routing-профиль не позволяет Xray запуститься (типичный случай — профиль ссылается на GeoIP/GeoSite-секцию, которой нет в текущем `.dat`), Fly Terminal не автоматизирует кнопки аварийного окна Happ. После неуспешного штатного запуска выполняется ровно одна безопасная повторная попытка через документированный `happ://routing/off`, то есть туннель запускается без routing-профиля. В UI такой успешный fallback явно помечается как **«без маршрутизации»**. При следующем выборе подписки, которая передаёт рабочий routing deeplink, её профиль снова применяется штатно.\n\nПервый запуск всегда выполняется с routing-профилем подписки: это даёт встроенному менеджеру Happ возможность обновить/атомарно заменить geofiles. Отключение маршрутизации используется только после фактического провала запуска, поэтому исправный split-routing не выключается заранее.\n'''
if "### Маршрутизация подписки и восстановление Xray" not in docs:
    docs = replace_once(docs, doc_marker, doc_marker + doc_addition, "TOOLS routing docs")
TOOLS.write_text(docs, encoding="utf-8")
