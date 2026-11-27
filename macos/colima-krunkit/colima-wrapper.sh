#!/bin/bash
# Deliberately scope the patched limactl to Colima; other Lima instances (Tailscale) keep Homebrew Lima.
set -euo pipefail
# Resolve the wrapper symlink (e.g. /opt/homebrew/bin/colima).
self="$0"
while [[ -L "$self" ]]; do
  link="$(readlink "$self")"
  [[ "$link" = /* ]] && self="$link" || self="$(dirname "$self")/$link"
done
root="$(cd "$(dirname "$self")" && pwd -P)"
export PATH="$root/lima-fixed/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec "$root/bin/colima-fixed-v2" "$@"
