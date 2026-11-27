#!/bin/bash
# Host-specific guarded migration. All VM data remains on the external SSD.
set -Eeuo pipefail
export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
live=$(readlink "$HOME/.colima")
base=$(dirname "$live")
w="$base/colima-0.10.2-krunkit-fix"
clone="$base/kt"
ts=$(date +%Y%m%d-%H%M%S)
backup="$base/fly-terminal-live-vz-pre-fixed-krunkit-$ts"
stage="$base/stage-fixed-krunkit-$ts"
failed="$base/failed-fixed-krunkit-$ts"
label=com.fly-terminal.colima
domain="gui/$(id -u)"
plist="$HOME/Library/LaunchAgents/$label.plist"
prefix="$HOME/Library/Application Support/FlyTerminal/colima-krunkit"
run="$prefix/colima-wrapper.sh"
exec > >(tee -a "$w/production-cutover-$ts.log") 2>&1
stamp(){ echo "===== $(date '+%T') $* ====="; }
state(){ env LIMA_HOME="$1" /opt/homebrew/bin/limactl list --json colima | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])'; }
[[ "$live" = "$base/fly-terminal-live" && -x "$run" && ! -e "$plist" ]]
grep -q 'FULL STACK TEST PASSED 2/2' "$w/full-stack-test.log"
# Prevent downtime until the same installed binary passes the launchd permission check.
for path in bin/colima-fixed-v2 lima-fixed/bin/limactl; do
  [[ "$(shasum -a 256 "$prefix/$path" | awk '{print $1}')" == "$(shasum -a 256 "$w/$path" | awk '{print $1}')" ]]
done
grep -q 'Virtualization.Framework' /opt/homebrew/var/log/colima-krunkit-permission.log
launchctl print "$domain/com.fly-terminal.colima-permission-check" | grep 'last exit code = 0' >/dev/null
[[ "$(state "$clone/_lima")" == Stopped && "$(state "$live/_lima")" == Running ]]
status_before=$(colima status 2>&1)
[[ "$status_before" == *Virtualization.Framework* ]]
mkdir -p "$backup/_lima/_disks" "$backup/_lima/_config" "$backup/check" "$stage/_lima/_disks/colima" "$stage/_lima/colima" "$stage/default"
chmod 700 "$backup" "$stage"
check="$backup/check"
migrating=0
rollback(){
 result=$?
 trap - EXIT HUP INT TERM
 [[ "$result" != 0 ]] || exit 0
 stamp "ROLLBACK result=$result"
 set +e
 if [[ "$migrating" == 1 ]]; then
  launchctl bootout "$domain/$label" 2>/dev/null || true
  if [[ "$(state "$live/_lima" 2>/dev/null)" == Running ]]; then
   "$run" stop || env LIMA_HOME="$live/_lima" "$w/lima-fixed/bin/limactl" stop colima || true
  fi
  if [[ "$(state "$live/_lima" 2>/dev/null)" == Running ]]; then echo "Candidate still running; disk moves refused"; exit 98; fi
  mkdir -p "$failed"
  for rel in default _lima/colima _lima/_disks/colima; do
   if [[ -e "$backup/$rel" ]]; then
    mkdir -p "$failed/$(dirname "$rel")"
    [[ ! -e "$live/$rel" ]] || mv "$live/$rel" "$failed/$rel"
    mv "$backup/$rel" "$live/$rel"
   fi
  done
  if [[ -f "$backup/_lima/_config/override.yaml" ]]; then
   cp -p "$backup/_lima/_config/override.yaml" "$live/_lima/_config/override.yaml"
  elif [[ -f "$live/_lima/_config/override.yaml" ]]; then
   mv "$live/_lima/_config/override.yaml" "$failed/colima-override.yaml"
  fi
  cp -p "$backup/colima.json" "$live/_store/colima.json"
  [[ ! -f "$plist" ]] || mv "$plist" "$failed/$label.plist"
 fi
 brew services start colima
 for n in {1..90}; do docker --context colima info >/dev/null 2>&1 && break; sleep 2; done
 colima status
 docker --context colima ps -a --format '{{.ID}} {{.Names}} {{.Status}}'
 echo "ROLLBACK_COMPLETE; failed candidate retained: $failed"
 exit "$result"
}
trap rollback EXIT
trap 'exit 130' HUP INT TERM
stamp "production baseline"
docker --context colima ps -aq --no-trunc | sort > "$check/containers"
docker --context colima volume ls -q | sort > "$check/volumes"
docker --context colima image ls -q --no-trunc | sort -u > "$check/images"
docker --context colima ps --format '{{.Names}}' | sort > "$check/running"
ps -p 80308,23539 -o pid=,command= > "$check/independent-vpn"
cp -p "$live/_store/colima.json" "$backup/colima.json"
if [[ -f "$live/_lima/_config/override.yaml" ]]; then cp -p "$live/_lima/_config/override.yaml" "$backup/_lima/_config/override.yaml"; fi
for f in disk lima.yaml lima-version colima.yaml; do cp -cRp "$clone/_lima/colima/$f" "$stage/_lima/colima/"; done
cp -p "$live/default/colima.yaml" "$stage/default/colima.yaml"
python3 - "$stage/default/colima.yaml" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
assert s.count('vmType: vz') == 1
p.write_text(s.replace('vmType: vz','vmType: krunkit'))
PY
stamp "stop VZ and clone current disk"
brew services stop colima
colima stop
[[ "$(state "$live/_lima")" == Stopped ]]
[[ ! -e "$live/_lima/_disks/colima/in_use_by" && ! -L "$live/_lima/_disks/colima/in_use_by" ]]
cp -cRp "$live/_lima/_disks/colima/datadisk" "$stage/_lima/_disks/colima/datadisk"
[[ "$(stat -f %z "$stage/_lima/_disks/colima/datadisk")" == "$(stat -f %z "$live/_lima/_disks/colima/datadisk")" ]]
[[ "$(stat -f %z "$stage/_lima/colima/disk")" == 21474836480 ]]
migrating=1
for rel in default _lima/colima _lima/_disks/colima; do
 mv "$live/$rel" "$backup/$rel"
 mv "$stage/$rel" "$live/$rel"
done
printf 'ssh:\n  overVsock: false\n' > "$live/_lima/_config/override.yaml"
stamp "install isolated launch agent (Homebrew CLI unchanged)"
python3 - "$plist" "$prefix" "$label" "$HOME" <<'PY'
import plistlib,sys
p,w,label,home=sys.argv[1:]
d={'Label':label,'ProgramArguments':['/bin/bash',w+'/colima-wrapper.sh','start','-f'],'RunAtLoad':True,
   'KeepAlive':{'SuccessfulExit':True},'WorkingDirectory':home,'ExitTimeOut':60,
   'StandardOutPath':'/opt/homebrew/var/log/colima-krunkit.log','StandardErrorPath':'/opt/homebrew/var/log/colima-krunkit.log'}
with open(p,'wb') as f: plistlib.dump(d,f)
PY
plutil -lint "$plist"
launchctl bootstrap "$domain" "$plist"
verify(){
 stamp "verify production ($1)"
 for n in {1..100}; do
  if docker --context colima info >/dev/null 2>&1 && "$run" status 2>&1 | grep -i krunkit >/dev/null; then break; fi
  sleep 2
 done
 "$run" status 2>&1 | tee "$check/status-$1"
 grep -qi krunkit "$check/status-$1"
 "$run" version
 docker context show | grep -qx colima
 "$run" ssh -- sh -ec 'for s in docker containerd cloud-final; do systemctl is-active "$s"; done; sudo grep -qx "LIMA_CIDATA_DISK_0_DEVICE=vdc" /mnt/lima-cidata/lima.env; findmnt -n -M /mnt/lima-colima -o SOURCE,LABEL,UUID,FSROOT,TARGET; findmnt -n -M /var/lib/docker -o SOURCE,LABEL,UUID,FSROOT,TARGET; /usr/local/sbin/colima-check-runtime-disk docker; /usr/local/sbin/colima-check-runtime-disk containerd; test "$(findmnt -n -M /mnt/lima-colima -o UUID)" = 0eb7dd38-5cad-4a0d-a26b-d88c29cc7c3b; df -h /var/lib/docker' </dev/null
 docker --context colima ps -aq --no-trunc | sort > "$check/actual-containers"
 docker --context colima volume ls -q | sort > "$check/actual-volumes"
 docker --context colima image ls -q --no-trunc | sort -u > "$check/actual-images"
 diff -u "$check/containers" "$check/actual-containers"
 diff -u "$check/volumes" "$check/actual-volumes"
 diff -u "$check/images" "$check/actual-images"
 for n in {1..45}; do
  chromium=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:7690/ 2>/dev/null || true)
  quasar=$(curl -ksS -o /dev/null -w '%{http_code}' --max-time 5 https://127.0.0.1:8443/ 2>/dev/null || true)
  [[ "$chromium" == 200 && "$quasar" == 404 ]] && break
  sleep 2
 done
 echo "Chromium=$chromium Quasar=$quasar"
 [[ "$chromium" == 200 && "$quasar" == 404 ]]
 docker --context colima ps --format '{{.Names}}' | sort > "$check/actual-running"
 diff -u "$check/running" "$check/actual-running"
 stamp "verify Quasar bind directory and executable"
 docker --context colima exec quasar-bridge-alice sh -ec 'test -d /auth; test -r /auth; test -f /bridge; test -r /bridge; test -x /bridge'
 echo "Quasar bind mounts verified"
 stamp "verify Gateway"
 gateway=$(curl -ksS -o /dev/null -w '%{http_code}' --max-time 15 https://commander-hub.tail1c55c5.ts.net/)
 [[ "$gateway" == 200 ]]
 echo "Gateway=$gateway"
 stamp "verify independent VPN processes"
 ps -p 80308,23539 -o pid=,command= > "$check/after-vpn"
 diff -u "$check/independent-vpn" "$check/after-vpn"
 launchctl print "$domain/$label" | grep -E 'state =|pid =|program ='
 stamp "production checks passed ($1)"
}
verify first
stamp "verify launch agent restart"
launchctl bootout "$domain/$label"
for n in {1..30}; do [[ "$(state "$live/_lima")" == Stopped ]] && break; sleep 2; done
if [[ "$(state "$live/_lima")" != Stopped ]]; then "$run" stop; fi
[[ "$(state "$live/_lima")" == Stopped ]]
launchctl bootstrap "$domain" "$plist"
verify restart
stamp "PRODUCTION CUTOVER PASSED"
printf '%s\n' "$backup" > "$w/production-backup-path"
trap - EXIT HUP INT TERM
