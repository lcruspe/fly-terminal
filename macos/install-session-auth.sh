#!/bin/zsh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
LOG_DIR="${HOME}/Library/Logs/fly-terminal"
LABEL="ai.kruspe.fly-terminal.session-auth"
AGENT="${HOME}/Library/LaunchAgents/${LABEL}.plist"
mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${HOME}/Library/LaunchAgents"
chmod 700 "${CONFIG_DIR}"
if [ ! -s "${CONFIG_DIR}/session-auth.secret" ]; then
  /opt/homebrew/bin/python3 - "${CONFIG_DIR}/session-auth.secret" <<'PY'
import os, pathlib, secrets, sys
path = pathlib.Path(sys.argv[1])
fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as out:
    out.write(secrets.token_urlsafe(48) + "\n")
PY
fi
chmod 600 "${CONFIG_DIR}/session-auth.secret"
export FLY_SESSION_AUTH_LAUNCH="${DIR}/launch-session-auth.sh"
export FLY_SESSION_AUTH_AGENT="${AGENT}"
export FLY_SESSION_AUTH_LOG_DIR="${LOG_DIR}"
/opt/homebrew/bin/python3 - <<'PY'
import os, pathlib, plistlib
plist = pathlib.Path(os.environ["FLY_SESSION_AUTH_AGENT"])
data = {
    "Label": "ai.kruspe.fly-terminal.session-auth",
    "ProgramArguments": ["/bin/zsh", os.environ["FLY_SESSION_AUTH_LAUNCH"]],
    "RunAtLoad": True, "KeepAlive": True,
    "StandardOutPath": os.environ["FLY_SESSION_AUTH_LOG_DIR"] + "/session-auth.log",
    "StandardErrorPath": os.environ["FLY_SESSION_AUTH_LOG_DIR"] + "/session-auth.err.log",
}
with plist.open("wb") as stream:
    plistlib.dump(data, stream)
PY
UID_VALUE="$(id -u)"
if launchctl print "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/${UID_VALUE}/${LABEL}"
else
  launchctl bootstrap "gui/${UID_VALUE}" "${AGENT}"
fi
