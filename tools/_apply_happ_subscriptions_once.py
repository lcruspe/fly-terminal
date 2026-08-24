#!/usr/bin/env python3
from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_section(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start] + replacement + text[end:]


# ---------------------------------------------------------------------------
# Backend: enumerate all Happ subscriptions from CFNetwork Cache.db and keep
# the legacy fsCachedData scan only as a compatibility fallback.
# ---------------------------------------------------------------------------
path = Path("session-control.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import mimetypes\n",
    "import mimetypes\nimport plistlib\nimport sqlite3\n",
    "backend imports",
)
text = replace_once(
    text,
    'HAPP_CACHE_DIR = Path.home() / "Library/Containers/su.ffg.happ.plus/Data/Library/Caches/su.ffg.happ.plus/fsCachedData"\n',
    'HAPP_CACHE_DIR = Path.home() / "Library/Containers/su.ffg.happ.plus/Data/Library/Caches/su.ffg.happ.plus/fsCachedData"\nHAPP_CACHE_DB = HAPP_CACHE_DIR.parent / "Cache.db"\n',
    "Happ cache database constant",
)
text = replace_once(
    text,
    '    "happ_location_not_found": "Выбранная локация Happ больше недоступна. Обновите список и выберите локацию заново.",\n',
    '    "happ_location_not_found": "Выбранная локация Happ больше недоступна. Обновите список и выберите локацию заново.",\n    "happ_subscription_not_found": "Выбранная подписка Happ больше недоступна. Обновите список подписок и повторите действие.",\n',
    "Happ subscription error message",
)

new_happ_catalog = r'''def _happ_config_id(config):
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def happ_current_config():
    try:
        result = subprocess.run(
            ["plutil", "-extract", "connectedConfigJson", "raw", "-o", "-", str(HAPP_PREFERENCES)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
        config = json.loads(result.stdout) if result.returncode == 0 else {}
        return config if isinstance(config, dict) else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}


def happ_current_location():
    return str(happ_current_config().get("remarks") or "").strip()


def _cached_value_bytes(value):
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return b""


def _happ_cached_response_body(receiver_data, is_data_on_fs):
    raw = _cached_value_bytes(receiver_data)
    if not raw:
        return b""

    file_name = ""
    try:
        file_name = raw.decode("utf-8").strip("\x00\r\n ")
    except UnicodeDecodeError:
        pass

    should_read_file = bool(is_data_on_fs)
    if not should_read_file and file_name and len(file_name) < 256:
        candidate = HAPP_CACHE_DIR / file_name
        should_read_file = candidate.is_file()

    if should_read_file and file_name and Path(file_name).name == file_name:
        try:
            return (HAPP_CACHE_DIR / file_name).read_bytes()
        except OSError:
            return b""
    return raw


def _parse_happ_subscription_configs(raw_body):
    if not raw_body:
        return []
    try:
        payload = json.loads(raw_body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        for key in ("configs", "servers", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []

    configs = []
    for config in payload:
        if not isinstance(config, dict) or not isinstance(config.get("outbounds"), list):
            continue
        label = str(config.get("remarks") or "").strip()
        if not label:
            continue
        configs.append(config)
    return configs


def _resolve_plist_archive(blob):
    raw = _cached_value_bytes(blob)
    if not raw:
        return None
    try:
        archive = plistlib.loads(raw)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return None
    if not isinstance(archive, dict) or not isinstance(archive.get("$objects"), list):
        return archive

    objects = archive["$objects"]

    def resolve(value, stack=frozenset()):
        if isinstance(value, plistlib.UID):
            index = value.data
            if index < 0 or index >= len(objects) or index in stack:
                return None
            return resolve(objects[index], stack | {index})
        if isinstance(value, list):
            return [resolve(item, stack) for item in value]
        if isinstance(value, dict):
            if "NS.keys" in value and "NS.objects" in value:
                keys = resolve(value["NS.keys"], stack)
                values = resolve(value["NS.objects"], stack)
                if isinstance(keys, list) and isinstance(values, list):
                    return {
                        str(key): item
                        for key, item in zip(keys, values)
                        if key is not None
                    }
            if "NS.objects" in value and set(value).issubset({"NS.objects", "$class"}):
                return resolve(value["NS.objects"], stack)
            return {
                str(key): resolve(item, stack)
                for key, item in value.items()
                if key != "$class"
            }
        return value

    return resolve(archive.get("$top", archive))


def _find_named_value(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("_", "-")
            if normalized in names and isinstance(item, (str, bytes, bytearray)):
                return item
        for item in value.values():
            found = _find_named_value(item, names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_named_value(item, names)
            if found not in (None, ""):
                return found
    return None


def _normalize_happ_subscription_title(value):
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    title = str(value or "").strip()
    if not title:
        return ""

    if " " not in title and len(title) >= 8 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", title):
        padded = title + "=" * (-len(title) % 4)
        try:
            decoded_bytes = base64.b64decode(padded, altchars=b"-_", validate=True)
            decoded = decoded_bytes.decode("utf-8").strip()
            standard = base64.b64encode(decoded_bytes).decode("ascii").rstrip("=")
            urlsafe = base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("=")
            if decoded and title.rstrip("=") in {standard, urlsafe} and all(char.isprintable() for char in decoded):
                title = decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return title[:80]


def _happ_subscription_title(response_object, request_key):
    archive = _resolve_plist_archive(response_object)
    title = _normalize_happ_subscription_title(
        _find_named_value(archive, {"profile-title", "profiletitle"})
    )
    if title:
        return title

    try:
        parsed = urlsplit(str(request_key or ""))
        host = parsed.hostname or ""
    except ValueError:
        host = ""
    return host or "Подписка Happ"


def _happ_locations_from_configs(configs):
    locations = []
    seen = set()
    for config in configs:
        location_id = _happ_config_id(config)
        if location_id in seen:
            continue
        seen.add(location_id)
        locations.append({
            "id": location_id,
            "label": str(config.get("remarks") or "").strip(),
            "config": config,
        })
    return locations


def _legacy_happ_subscriptions():
    """Compatibility fallback for installations where Cache.db cannot be read."""
    try:
        cache_files = sorted(HAPP_CACHE_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return []

    subscriptions = []
    fingerprints = set()
    for cache_file in cache_files:
        try:
            configs = _parse_happ_subscription_configs(cache_file.read_bytes())
        except OSError:
            continue
        locations = _happ_locations_from_configs(configs)
        if not locations:
            continue
        fingerprint = hashlib.sha256("|".join(item["id"] for item in locations).encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        subscriptions.append({
            "id": f"legacy-{fingerprint[:16]}",
            "label": "Подписка Happ",
            "locations": locations,
        })
    return subscriptions


def happ_subscriptions():
    """Return every cached Happ subscription and its locations without exposing subscription URLs."""
    if not HAPP_CACHE_DB.is_file():
        subscriptions = _legacy_happ_subscriptions()
    else:
        subscriptions = []
        seen_subscriptions = set()
        connection = None
        try:
            database_uri = f"file:{quote(str(HAPP_CACHE_DB), safe='/')}?mode=ro"
            connection = sqlite3.connect(database_uri, uri=True, timeout=1)
            receiver_columns = {
                str(row[1]).casefold(): str(row[1])
                for row in connection.execute("PRAGMA table_info(cfurl_cache_receiver_data)")
            }
            response_columns = {
                str(row[1]).casefold(): str(row[1])
                for row in connection.execute("PRAGMA table_info(cfurl_cache_response)")
            }
            if "isdataonfs" in receiver_columns:
                fs_expr = f'd."{receiver_columns["isdataonfs"]}"'
            elif "isdataonfs" in response_columns:
                fs_expr = f'r."{response_columns["isdataonfs"]}"'
            else:
                fs_expr = "0"

            rows = connection.execute(
                f"""
                SELECT r.entry_ID, r.request_key, r.time_stamp,
                       {fs_expr} AS is_data_on_fs,
                       d.receiver_data, b.response_object
                FROM cfurl_cache_response AS r
                JOIN cfurl_cache_receiver_data AS d USING (entry_ID)
                LEFT JOIN cfurl_cache_blob_data AS b USING (entry_ID)
                ORDER BY r.time_stamp DESC
                """
            )
            for entry_id, request_key, _timestamp, is_data_on_fs, receiver_data, response_object in rows:
                body = _happ_cached_response_body(receiver_data, is_data_on_fs)
                configs = _parse_happ_subscription_configs(body)
                locations = _happ_locations_from_configs(configs)
                if not locations:
                    continue

                stable_key = str(request_key or f"cache-entry:{entry_id}")
                subscription_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:24]
                if subscription_id in seen_subscriptions:
                    continue
                seen_subscriptions.add(subscription_id)
                subscriptions.append({
                    "id": subscription_id,
                    "label": _happ_subscription_title(response_object, request_key),
                    "locations": locations,
                })
        except (OSError, sqlite3.Error):
            subscriptions = []
        finally:
            if connection is not None:
                connection.close()

        if not subscriptions:
            subscriptions = _legacy_happ_subscriptions()

    label_counts = {}
    for subscription in subscriptions:
        base_label = subscription.get("label") or "Подписка Happ"
        count = label_counts.get(base_label, 0) + 1
        label_counts[base_label] = count
        if count > 1:
            subscription["label"] = f"{base_label} ({count})"
    return subscriptions


def happ_subscription_catalog():
    subscriptions = happ_subscriptions()
    current_config = happ_current_config()
    current_label = str(current_config.get("remarks") or "").strip()
    current_config_id = _happ_config_id(current_config) if current_config else ""
    current_subscription_id = ""
    current_location_id = ""

    if current_config_id:
        for subscription in subscriptions:
            location = next((item for item in subscription["locations"] if item["id"] == current_config_id), None)
            if location:
                current_subscription_id = subscription["id"]
                current_location_id = location["id"]
                break

    if not current_subscription_id and current_label:
        matches = [
            (subscription, location)
            for subscription in subscriptions
            for location in subscription["locations"]
            if location["label"] == current_label
        ]
        if len(matches) == 1:
            current_subscription_id = matches[0][0]["id"]
            current_location_id = matches[0][1]["id"]

    current_subscription_label = next(
        (item["label"] for item in subscriptions if item["id"] == current_subscription_id),
        "",
    )
    return {
        "subscriptions": subscriptions,
        "current": current_label,
        "currentSubscriptionId": current_subscription_id,
        "currentSubscription": current_subscription_label,
        "currentLocationId": current_location_id,
    }


'''
text = replace_section(
    text,
    "def happ_current_location():\n",
    "def apply_happ_location(location):\n",
    new_happ_catalog,
    "Happ catalog functions",
)

old_locations_route = '''        if self.path == "/api/vpn/happ/locations":
            locations = happ_locations()
            current = happ_current_location()
            send_json(self, 200, {
                "ok": True,
                "current": current,
                "locations": [{"id": item["id"], "label": item["label"]} for item in locations],
                "configured": bool(locations),
            })
            return

'''
new_locations_route = '''        if self.path in {"/api/vpn/happ/locations", "/api/vpn/happ/subscriptions"}:
            catalog = happ_subscription_catalog()
            public_subscriptions = [
                {
                    "id": subscription["id"],
                    "label": subscription["label"],
                    "locations": [
                        {"id": location["id"], "label": location["label"]}
                        for location in subscription["locations"]
                    ],
                }
                for subscription in catalog["subscriptions"]
            ]
            send_json(self, 200, {
                "ok": True,
                "current": catalog["current"],
                "currentSubscriptionId": catalog["currentSubscriptionId"],
                "currentSubscription": catalog["currentSubscription"],
                "currentLocationId": catalog["currentLocationId"],
                "subscriptions": public_subscriptions,
                "configured": bool(public_subscriptions),
            })
            return

'''
text = replace_once(text, old_locations_route, new_locations_route, "Happ subscriptions route")

new_happ_handler = '''    def _handle_happ_location(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        subscription_id = str(payload.get("subscriptionId") or "")
        location_id = str(payload.get("locationId") or "")
        catalog = happ_subscription_catalog()
        subscriptions = catalog["subscriptions"]

        subscription = None
        if subscription_id:
            subscription = next((item for item in subscriptions if item["id"] == subscription_id), None)
            if not subscription:
                send_json(self, 404, {"ok": False, "error": "happ_subscription_not_found"})
                return
            candidates = subscription["locations"]
        else:
            candidates = [location for item in subscriptions for location in item["locations"]]

        location = next((item for item in candidates if item["id"] == location_id), None)
        if not location:
            send_json(self, 404, {"ok": False, "error": "happ_location_not_found"})
            return
        if not HAPP_RECONNECT_LOCK.acquire(blocking=False):
            send_json(self, 409, {"ok": False, "error": "happ_action_already_running"})
            return
        try:
            switched, switch_error = apply_happ_location(location)
            final_state, final_error = happ_vpn_status()
            if not switched:
                send_json(self, 504, {"ok": False, "error": "happ_location_switch_failed", "state": final_state, "details": switch_error or final_error})
                return
            send_json(self, 200, {
                "ok": True,
                "service": HAPP_VPN_SERVICE,
                "state": final_state,
                "subscriptionId": subscription["id"] if subscription else "",
                "subscription": subscription["label"] if subscription else "",
                "location": happ_current_location() or location["label"],
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            send_json(self, 500, {"ok": False, "error": "happ_location_switch_failed", "details": str(exc)})
        finally:
            HAPP_RECONNECT_LOCK.release()

'''
text = replace_section(
    text,
    "    def _handle_happ_location(self):\n",
    "    def _handle_terminate(self):\n",
    new_happ_handler,
    "Happ location handler",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontend: dependent subscription -> location selects.
# ---------------------------------------------------------------------------
path = Path("index.html")
text = path.read_text(encoding="utf-8")
old_happ_markup = '''              <div class="settings-group">
                <span class="settings-label">Локация Happ</span>
                <select id="happLocation" aria-label="Локация Happ"><option value="">Загрузка...</option></select>
                <div class="settings-action-status" id="happLocationStatus"></div>
              </div>
'''
new_happ_markup = '''              <div class="settings-group">
                <span class="settings-label">Подписка Happ</span>
                <select id="happSubscription" aria-label="Подписка Happ"><option value="">Загрузка...</option></select>
                <span class="settings-label">Локация</span>
                <select id="happLocation" aria-label="Локация Happ"><option value="">Сначала выберите подписку</option></select>
                <div class="settings-action-status" id="happLocationStatus"></div>
              </div>
'''
text = replace_once(text, old_happ_markup, new_happ_markup, "Happ two-select markup")
text = replace_once(
    text,
    '    const happStatus = document.getElementById("happStatus");\n    const happLocationSelect = document.getElementById("happLocation");\n',
    '    const happStatus = document.getElementById("happStatus");\n    const happSubscriptionSelect = document.getElementById("happSubscription");\n    const happLocationSelect = document.getElementById("happLocation");\n',
    "Happ subscription UI reference",
)
text = replace_once(
    text,
    '    let browserApps = [];\n    let browserAppsError = "";\n',
    '    let browserApps = [];\n    let browserAppsError = "";\n    let happSubscriptions = [];\n    let happCatalogState = { currentSubscriptionId: "", currentLocationId: "", current: "", currentSubscription: "" };\n',
    "Happ catalog UI state",
)
text = replace_once(
    text,
    '      if (payload?.location && happLocationStatus) happLocationStatus.textContent = `Сейчас: ${payload.location}`;\n',
    '      if (payload?.location && happLocationStatus) {\n        happLocationStatus.textContent = payload?.subscription\n          ? `Сейчас: ${payload.subscription} → ${payload.location}`\n          : `Сейчас: ${payload.location}`;\n      }\n',
    "Happ current state label",
)

new_happ_ui_functions = r'''    function renderHappLocationOptions(subscriptionId, preferredLocationId = "") {
      if (!happLocationSelect) return;
      happLocationSelect.innerHTML = "";
      const subscription = happSubscriptions.find(item => item.id === subscriptionId);
      if (!subscription) {
        happLocationSelect.appendChild(new Option("Сначала выберите подписку", ""));
        happLocationSelect.disabled = true;
        return;
      }

      const locations = Array.isArray(subscription.locations) ? subscription.locations : [];
      if (!locations.length) {
        happLocationSelect.appendChild(new Option("Нет доступных локаций", ""));
        happLocationSelect.disabled = true;
        return;
      }

      happLocationSelect.appendChild(new Option("Выберите локацию…", ""));
      locations.forEach(location => happLocationSelect.appendChild(new Option(location.label, location.id)));
      happLocationSelect.disabled = false;
      if (preferredLocationId && locations.some(location => location.id === preferredLocationId)) {
        happLocationSelect.value = preferredLocationId;
      }
    }

    function updateHappCatalogStatus(selectedSubscriptionId = "") {
      if (!happLocationStatus) return;
      if (happCatalogState.current) {
        const subscriptionLabel = happCatalogState.currentSubscription || "";
        happLocationStatus.textContent = subscriptionLabel
          ? `Сейчас: ${subscriptionLabel} → ${happCatalogState.current}`
          : `Сейчас: ${happCatalogState.current}`;
        return;
      }
      const selected = happSubscriptions.find(item => item.id === selectedSubscriptionId);
      happLocationStatus.textContent = selected ? `Подписка: ${selected.label}` : "";
    }

    async function loadHappSubscriptions() {
      if (!happSubscriptionSelect || !happLocationSelect) return;
      try {
        const response = await localApiFetch("/api/vpn/happ/subscriptions");
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.message || payload.details || "Не удалось получить подписки Happ");
        }

        happSubscriptions = Array.isArray(payload.subscriptions) ? payload.subscriptions : [];
        happCatalogState = {
          currentSubscriptionId: payload.currentSubscriptionId || "",
          currentLocationId: payload.currentLocationId || "",
          current: payload.current || "",
          currentSubscription: payload.currentSubscription || ""
        };

        happSubscriptionSelect.innerHTML = "";
        if (!happSubscriptions.length) {
          happSubscriptionSelect.appendChild(new Option("Подписки не найдены", ""));
          happSubscriptionSelect.disabled = true;
          renderHappLocationOptions("");
          happLocationStatus.textContent = "В кэше Happ не найдены подписки с доступными локациями";
          return;
        }

        happSubscriptionSelect.appendChild(new Option("Выберите подписку…", ""));
        happSubscriptions.forEach(subscription => {
          happSubscriptionSelect.appendChild(new Option(subscription.label, subscription.id));
        });
        happSubscriptionSelect.disabled = false;

        const currentExists = happSubscriptions.some(item => item.id === happCatalogState.currentSubscriptionId);
        const selectedSubscriptionId = currentExists
          ? happCatalogState.currentSubscriptionId
          : happSubscriptions[0].id;
        happSubscriptionSelect.value = selectedSubscriptionId;
        renderHappLocationOptions(
          selectedSubscriptionId,
          selectedSubscriptionId === happCatalogState.currentSubscriptionId ? happCatalogState.currentLocationId : ""
        );
        updateHappCatalogStatus(selectedSubscriptionId);
      } catch (error) {
        happSubscriptions = [];
        happSubscriptionSelect.innerHTML = "";
        happSubscriptionSelect.appendChild(new Option("Недоступно", ""));
        happSubscriptionSelect.disabled = true;
        renderHappLocationOptions("");
        happLocationStatus.textContent = `Ошибка: ${error.message || error}`;
      }
    }

    function handleHappSubscriptionChange() {
      const subscriptionId = happSubscriptionSelect?.value || "";
      const preferredLocationId = subscriptionId === happCatalogState.currentSubscriptionId
        ? happCatalogState.currentLocationId
        : "";
      renderHappLocationOptions(subscriptionId, preferredLocationId);
      updateHappCatalogStatus(subscriptionId);
    }

    async function switchHappLocation() {
      const subscriptionId = happSubscriptionSelect?.value || "";
      const locationId = happLocationSelect?.value || "";
      if (!subscriptionId || !locationId) return;

      const subscription = happSubscriptions.find(item => item.id === subscriptionId);
      const selectedLabel = happLocationSelect.options[happLocationSelect.selectedIndex]?.textContent || "локацию";
      const subscriptionLabel = subscription?.label || "подписка";
      happSubscriptionSelect.disabled = true;
      happLocationSelect.disabled = true;
      reconnectHappBtn.disabled = true;
      happLocationStatus.textContent = `Переключаю: ${subscriptionLabel} → ${selectedLabel}...`;
      try {
        const response = await localApiFetch("/api/vpn/happ/location", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subscriptionId, locationId })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.message || payload.details || "Не удалось переключить локацию Happ");
        }
        renderHappState(payload);
        setStatusText(`Happ: ${payload.subscription || subscriptionLabel} → ${payload.location || selectedLabel}`, 2800);
      } catch (error) {
        happLocationStatus.textContent = `Ошибка: ${error.message || error}`;
        setStatusText("Не удалось переключить локацию Happ", 3600);
      } finally {
        reconnectHappBtn.disabled = false;
        await loadHappSubscriptions();
      }
    }

'''
text = replace_section(
    text,
    "    async function loadHappLocations() {\n",
    "    async function refreshHappStatus() {\n",
    new_happ_ui_functions,
    "Happ dependent selects UI",
)
text = replace_once(
    text,
    '''    if (happLocationSelect) {
      happLocationSelect.onchange = switchHappLocation;
      loadHappLocations();
    }
''',
    '''    if (happSubscriptionSelect && happLocationSelect) {
      happSubscriptionSelect.onchange = handleHappSubscriptionChange;
      happLocationSelect.onchange = switchHappLocation;
      loadHappSubscriptions();
    }
''',
    "Happ listeners",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Documentation.
# ---------------------------------------------------------------------------
path = Path("TOOLS.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "- **Локация Happ** — чтение доступных конфигураций из кэша Happ Plus и переключение текущей локации.\n",
    "- **Подписка и локация Happ** — выбор подписки, затем одной из локаций этой подписки; список строится по локальному CFNetwork-кэшу Happ Plus.\n",
    "TOOLS Happ summary",
)
happ_docs_anchor = "### Восстановление Chromium\n"
happ_docs = '''### Подписки и локации Happ

В Tools используются два зависимых меню: **Подписка Happ** и **Локация**. При смене подписки второе меню перестраивается только по локациям выбранной подписки; переключение VPN выполняется после выбора конкретной локации.

Источник данных — системный CFNetwork-кэш Happ Plus: `Cache.db` в `~/Library/Containers/su.ffg.happ.plus/Data/Library/Caches/su.ffg.happ.plus/`. Backend связывает `cfurl_cache_response.request_key` с `cfurl_cache_receiver_data`: если тело вынесено на диск, имя файла берётся из `receiver_data` и читается из `fsCachedData`; небольшие ответы читаются непосредственно из BLOB. Благодаря этому перечисляются все закэшированные подписки, а не только самый свежий файл `fsCachedData`.

Название подписки извлекается из HTTP-метаданных `profile-title` в `response_object` (включая base64-вариант, поддерживаемый Happ). Если заголовок недоступен, UI получает только безопасное имя хоста; полный URL подписки и его токены наружу не выдаются. ID подписки — SHA-256 от `request_key`, ID локации — SHA-256 от нормализованного JSON-конфига.

`GET /api/vpn/happ/subscriptions` возвращает `subscriptions[]`, внутри каждой — `locations[]`, а также `currentSubscriptionId` и `currentLocationId`, если текущий `connectedConfigJson` удалось сопоставить с кэшем. Старый `GET /api/vpn/happ/locations` сохранён как совместимый alias того же каталога. `POST /api/vpn/happ/location` принимает `subscriptionId` + `locationId`; перед применением backend проверяет, что локация действительно принадлежит выбранной подписке.

Если `Cache.db` отсутствует или недоступен, остаётся fallback на прямое чтение `fsCachedData`. В этом режиме локации продолжают работать, но название подписки может быть обобщённым.

'''
if happ_docs not in text:
    text = replace_once(text, happ_docs_anchor, happ_docs + happ_docs_anchor, "TOOLS Happ architecture")
path.write_text(text, encoding="utf-8")
