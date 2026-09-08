#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/webrtc-bridge"
BUILD_ROOT="${FLY_WEBRTC_BUILD_ROOT:-/Volumes/WD/fly-terminal-build}"
CARGO_HOME_DIR="${BUILD_ROOT}/cargo-home"
TARGET_DIR="${BUILD_ROOT}/webrtc-target"
RUNTIME_BIN_DIR="${FLY_WEBRTC_RUNTIME_BIN_DIR:-${HOME}/.local/share/fly-terminal/bin}"
BIN_PATH="${RUNTIME_BIN_DIR}/fly-webrtc-bridge"
LOCK_DIR="${BUILD_ROOT}/webrtc-build.lock"

if [ ! -d "/Volumes/WD" ]; then
  echo "WD volume is required for WebRTC build artifacts." >&2
  exit 1
fi
command -v cargo >/dev/null 2>&1 || { echo "cargo is not installed." >&2; exit 1; }
mkdir -p "${BUILD_ROOT}" "${CARGO_HOME_DIR}" "${TARGET_DIR}" "${RUNTIME_BIN_DIR}"

while ! mkdir "${LOCK_DIR}" 2>/dev/null; do sleep 0.5; done
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

needs_build=0
[ -x "${BIN_PATH}" ] || needs_build=1
if [ "${needs_build}" = "0" ] && find "${SOURCE_DIR}" -type f \( -name '*.rs' -o -name 'Cargo.toml' -o -name 'Cargo.lock' \) -newer "${BIN_PATH}" -print -quit | grep -q .; then
  needs_build=1
fi
if [ "${needs_build}" = "1" ]; then
  echo "Building Fly WebRTC bridge on WD..." >&2
  export CARGO_HOME="${CARGO_HOME_DIR}"
  export CARGO_TARGET_DIR="${TARGET_DIR}"
  cargo build --release --locked --manifest-path "${SOURCE_DIR}/Cargo.toml"
  tmp_bin="${BIN_PATH}.tmp.$$"
  install -m 755 "${TARGET_DIR}/release/fly-webrtc-bridge" "${tmp_bin}"
  mv -f "${tmp_bin}" "${BIN_PATH}"
fi

printf '%s\n' "${BIN_PATH}"
