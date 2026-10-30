# ATLAS Network Map

Read-only live observability web application integrated into Mac Gateway (Fly Terminal). No npm, no build step, no elevated privileges, and no changes to VPN or routing configuration.

## Access

- Private tailnet: `https://mac-gateway.tail1c55c5.ts.net/network-map/`.
- Mac's existing gateway: `http://127.0.0.1:8080/network-map/` (requires Gateway credentials).
- Application itself: `127.0.0.1:7799` (only loopback; not an independent external entry point).

Caddy routes `/network-map/*` to `127.0.0.1:7799` using `handle_path`, **without adding the route to the unauthenticated path exceptions**. The existing Gateway authentication still protects it; Linux/Tailscale SSO remains unchanged.

## Architecture

- `server.py` — standard-library HTTP server; `ThreadPoolExecutor` for bounded HTTP/TCP probes; read-only Tailscale state via `limactl shell ts tailscale status --json`; Amnezia read-only process/route inspection; SQLite history.
- `index.html`, `style.css`, `app.js` — self-contained Russian-language dashboard, responsive on phones and desktop, interactive SVG topology, clickable node inspector, service health, status table, rolling status events, 15-second client refresh.
- `favicon.svg` — application mark.
- macOS LaunchAgent `ai.kruspe.network-map` — user-level autostart and crash recovery. Logs: `~/Library/Logs/NetworkMap/`.
- Persistent SQLite database is located on `/Volumes/MacSSD — данные/Infrastructure/NetworkMap/monitor.sqlite3` if that volume exists; otherwise at `~/Library/Application Support/NetworkMap/monitor.sqlite3`. The app keeps running and displays live state if the history volume becomes unavailable.

## Monitoring semantics

- 11 curated nodes: internet, home router, Mac Mini, Linux/Tailscale VM, OpenWrt, Sprut.Hub, Mate, iPhone, MacBook, Commander Hub, Oracle HTTPS relay.
- 14 service checks cover Fly Terminal, desktop WebRTC/streamers, Chromium, RoomAudio, YT Transcript, gateway control, Sprut.Hub, LuCI, router, public relay, and external HTTPS.
- HTTP 2xx/3xx, HTTP 401 and 403 indicate *responsive* service (some require login); HTTP 404/410/429 indicate degraded route; 5xx, refused connection and timeouts indicate failed probe. TCP availability does **not** prove full end-to-end application operation.
- Tailscale peer state means *reachability through this tailnet*, not whether a device is powered on or otherwise reachable (e.g. via RDC). An offline Mate Tailscale peer **does not imply Mate is shut down**.
- Topology edges show known logical/physical relationships and peer connectivity; they are **not packet-level path tracing** or proof of a particular ISP route.
- Amnezia state is positive only when its process exists and macOS has a `utun` default-route interface.
- Polling interval: 30 seconds. TCP/HTTP probes are asynchronous with short timeouts. Web clients refresh cached state every 15 seconds. No active network scans, device discovery, traffic interception, or routing changes.
- History includes node **and service** state; rolling 7-day samples and 30-day transition events. Uptime percentage is over *available observations in the past 24 hours*; during a new installation it does not claim 24 hours of monitoring.

## Operator commands

```sh
launchctl print "gui/$(id -u)/ai.kruspe.network-map"
launchctl kickstart -k "gui/$(id -u)/ai.kruspe.network-map"
curl -s http://127.0.0.1:7799/healthz
curl -s http://127.0.0.1:7799/api/snapshot
curl -s http://127.0.0.1:7799/api/history
tail -80 ~/Library/Logs/NetworkMap/server.log
```

To add a monitored node, append its record to `NODE_DEFS` in `server.py`, add services as necessary to `SERVICES`, add an `EDGES` relationship, and provide canvas coordinates for that node in `app.js` (`point` map). To add a new external link, extend `hrefFor` on the frontend; never expose credentials there.

## Security and rollback

- No cookies, passwords, authentication tokens, private keys or user content are collected or exposed by the monitor.
- The HTTP backend accepts GET/HEAD only, listens only on localhost and serves four allowlisted static paths plus bounded JSON APIs.
- Gateway Caddy enforces the existing authentication. There is no public-open metrics endpoint.
- All observation checks are read-only. Amnezia, Tailscale, existing Colima, RoomAudio, Fly Terminal and Oracle Relay are not restarted or modified by this application.
- Disable: `launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/ai.kruspe.network-map.plist`. Remove the new Caddy handler and Gateway catalog card if full rollback is needed. Database and source files remain until explicitly deleted.

## Planned extensions

Editable node definitions; paired local/remote vantage-point checks; per-service SLOs and alert notifications; detailed latency trends and Wi-Fi link diagnostics. These are **not** claimed as implemented in v1.
