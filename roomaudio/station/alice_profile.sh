#!/bin/sh
# Temporary capture profile. A stale or disconnected reader restores stock Quasar.
set -eu
D=/data/opt/roomaudio-alice
Q=/system/vendor/quasar
LOCK="$D/active"
restore() {
  mkdir "$D/restoring" 2>/dev/null || return 0
  rm -f "$D/lease" "$D/microphone.sock" "$D/receiver.pid"
  "$Q/q" restart >/dev/null 2>&1 || true
  rm -rf "$LOCK" "$D/restoring"
}
case "${1:-}" in
 watchdog)
  sleep 35
  while [ -d "$LOCK" ]; do
   now=$(date +%s); last=$(cat "$D/lease" 2>/dev/null || echo 0)
   case "$last" in ''|*[!0-9]*) last=0;; esac
   if [ $((now-last)) -gt 20 ]; then restore; exit 0; fi
   sleep 5
  done
  ;;
 stream)
  umask 077
  [ -x "$D/alice_receiver" ] && [ -s "$D/vqe_tap.so" ] && [ -s "$D/launch.capture.json" ] || { echo 'Capture helper is incomplete' >&2; exit 1; }
  tap_hash=$(sha256sum "$D/vqe_tap.so" | cut -d ' ' -f 1)
  [ "$tap_hash" = '9a237062255c9fc44e4666a3e1273e33064f652b9428fb06781ee7df17a7a22b' ] || { echo 'Microphone helper checksum mismatch' >&2; exit 1; }
  main_hash=$(sha256sum "$Q/maind" | cut -d ' ' -f 1)
  vqe_hash=$(sha256sum "$Q/libs/libyandex_evil.so" | cut -d ' ' -f 1)
  [ "$main_hash" = '2dad0ffc61ba73d15ea813b754d7a56866d0477c321dcad9138b8d06e14ddbf1' ] && [ "$vqe_hash" = 'df67c7ad9fb9f2f9c473ba2aaed7663a0e898a2c6622993e65d3b8834a0b3646' ] || { echo 'Unverified firmware: microphone capture disabled' >&2; exit 1; }
  expected=$(cat "$D/launch.sha256" 2>/dev/null || true)
  actual=$(sha256sum "$Q/launch.json" | cut -d ' ' -f 1)
  [ -n "$expected" ] && [ "$actual" = "$expected" ] || { echo 'Quasar configuration changed; capture profile must be rebuilt' >&2; exit 1; }
  mkdir "$LOCK" 2>/dev/null || { echo 'Another listener is active' >&2; exit 1; }
  trap 'restore' EXIT HUP INT TERM
  rm -f "$D/lease" "$D/microphone.sock" "$D/receiver.pid"
  nohup "$D/profile.sh" watchdog >"$D/watchdog.log" 2>&1 </dev/null &
  "$Q/q" stop >/dev/null 2>&1 || true
  if pidof quasar_launcher2 >/dev/null; then echo 'Unable to stop Quasar' >&2; exit 1; fi
  cd /data/quasar
  export CA_CERTIFICATES="$Q/ca-certificates.crt" LD_LIBRARY_PATH="$Q/libs"
  ulimit -n 10240
  ulimit -s 1024
  nohup "$Q/quasar_launcher2" "$D/launch.capture.json" >"$D/launcher.log" 2>&1 </dev/null &
  "$D/alice_receiver" "$D/microphone.sock" "$D/lease" &
  receiver=$!
  echo "$receiver" > "$D/receiver.pid"
  wait "$receiver"
  ;;
 stop)
  if [ -s "$D/receiver.pid" ]; then
   receiver=$(cat "$D/receiver.pid")
   case "$receiver" in ''|*[!0-9]*) receiver=0;; esac
   if [ "$receiver" -gt 0 ] && [ -r "/proc/$receiver/cmdline" ]; then
    command=$(tr '\000' ' ' < "/proc/$receiver/cmdline")
    case "$command" in "$D/alice_receiver"*) kill "$receiver" 2>/dev/null || true;; esac
   fi
  fi
  # Give the stream owner time to run its EXIT trap before recovering directly.
  for i in $(seq 1 15); do
   [ -d "$LOCK" ] || exit 0
   sleep 1
  done
  [ ! -d "$LOCK" ] || restore
  ;;
 *) echo 'Usage: profile.sh stream|stop|watchdog' >&2; exit 2;;
esac
