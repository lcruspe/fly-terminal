#!/bin/zsh
# Idempotent local-only installer. Does not change any VPN or Caddy route.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/ai.kruspe.network-map.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/NetworkMap"
/usr/bin/python3 - "$SCRIPT_DIR" "$PLIST" <<'PY'
from pathlib import Path
import plistlib,sys
folder=Path(sys.argv[1]);out=Path(sys.argv[2]);python='/opt/homebrew/bin/python3'
d={'Label':'ai.kruspe.network-map','ProgramArguments':[python,str(folder/'server.py')],
'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':12,'ProcessType':'Background',
'WorkingDirectory':str(folder),'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','NETWORKMAP_PORT':'7799','NETWORKMAP_INTERVAL':'30'},
'StandardOutPath':str(Path.home()/'Library/Logs/NetworkMap/server.log'),
'StandardErrorPath':str(Path.home()/'Library/Logs/NetworkMap/error.log')}
with out.open('wb') as f:plistlib.dump(d,f)
PY
plutil -lint "$PLIST"
if launchctl print "gui/$(id -u)/ai.kruspe.network-map" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/ai.kruspe.network-map" || true
fi
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Network Map installed. Local health: http://127.0.0.1:7799/healthz"
