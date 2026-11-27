#!/bin/bash
# Non-disruptive TCC preflight under the same login launchd context as production.
set -euo pipefail
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
prefix="$HOME/Library/Application Support/FlyTerminal/colima-krunkit"
label=com.fly-terminal.colima-permission-check
domain="gui/$(id -u)"
plist="$HOME/Library/LaunchAgents/$label.plist"
log="/opt/homebrew/var/log/colima-krunkit-permission.log"
[[ -x "$prefix/bin/colima-fixed-v2" && -x "$prefix/lima-fixed/bin/limactl" ]]
if launchctl print "$domain/$label" >/dev/null 2>&1; then launchctl bootout "$domain/$label"; fi
if [[ -f "$log" ]]; then mv "$log" "$log.$(date +%Y%m%d-%H%M%S)"; fi
python3 - "$plist" "$prefix" "$label" "$log" "$HOME" <<'PY'
import sys,plistlib
p,root,label,log,home=sys.argv[1:]
d={'Label':label,'ProgramArguments':['/bin/bash',root+'/colima-wrapper.sh','status'],
   'RunAtLoad':True,'WorkingDirectory':home,'StandardOutPath':log,'StandardErrorPath':log}
with open(p,'wb') as f: plistlib.dump(d,f)
PY
plutil -lint "$plist"
launchctl bootstrap "$domain" "$plist"
echo "Read-only permission preflight: $label"
echo "Approve only the macOS prompt for removable-volume access for colima-fixed-v2 if it appears."
