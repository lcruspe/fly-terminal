#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export FLY_GATEWAY_SCRIPT_DIR="$SCRIPT_DIR"
/opt/homebrew/bin/python3 - <<'PY'
import os, pathlib, plistlib
home = pathlib.Path.home()
script = pathlib.Path(os.environ['FLY_GATEWAY_SCRIPT_DIR']) / 'launch-gateway-control.sh'
log = home / 'Library/Logs/fly-terminal'
log.mkdir(parents=True, exist_ok=True)
agent = home / 'Library/LaunchAgents/ai.kruspe.fly-terminal.gateway-control.plist'
agent.parent.mkdir(parents=True, exist_ok=True)
with agent.open('wb') as f:
    plistlib.dump({'Label':'ai.kruspe.fly-terminal.gateway-control',
                  'ProgramArguments':['/bin/zsh',str(script)],'RunAtLoad':True,'KeepAlive':True,
                  'StandardOutPath':str(log/'gateway-control.log'),
                  'StandardErrorPath':str(log/'gateway-control.err.log')}, f)
PY
launchctl bootout "gui/$(id -u)/ai.kruspe.fly-terminal.gateway-control" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/ai.kruspe.fly-terminal.gateway-control.plist"
