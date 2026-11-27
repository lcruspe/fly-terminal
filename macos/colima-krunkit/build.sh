#!/bin/bash
# Reproducible isolated build; never modifies the installed Homebrew binaries.
set -euo pipefail
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
patches="$(cd "$(dirname "$0")" && pwd)"
work="${1:?Usage: build.sh /absolute/path/on/external-ssd/fresh-directory}"
[[ "$work" = /* && ! -e "$work" ]] || { echo "Use a new absolute build directory" >&2; exit 2; }
[[ "$(uname -m)" = arm64 && "$(uname -s)" = Darwin ]]
mkdir -p "$work"/{toolchain,cache,mod,tmp,bin,lima-fixed/bin,lima-fixed/share,lima-fixed/libexec}
cd "$work"
curl -fL --retry 2 -o go.tar.gz https://go.dev/dl/go1.25.14.darwin-arm64.tar.gz
printf '%s  %s\n' 5b26c0b6f308240fca2614fb02f622cfcc8c0cc3b69c78bba4845489a4590259 go.tar.gz | shasum -a 256 -c
tar -xzf go.tar.gz -C toolchain
export PATH="$work/toolchain/go/bin:$PATH" GOCACHE="$work/cache" GOMODCACHE="$work/mod" TMPDIR="$work/tmp" GOMAXPROCS=2
git clone --depth 1 --branch v0.10.2 https://github.com/abiosoft/colima.git src
git clone --depth 1 --branch v2.1.2 https://github.com/lima-vm/lima.git lima-src
cd "$work/src"
test "$(git rev-parse HEAD)" = 1afe7c4771501eaae2dc1cbe506c4a67609ed151
git apply --check "$patches/colima-0.10.2.patch"
git apply "$patches/colima-0.10.2.patch"
go test -p 2 ./environment/vm/lima
go build -p 2 -ldflags="-s -w -X github.com/abiosoft/colima/config.appVersion=0.10.2-krunkit-fix.2 -X github.com/abiosoft/colima/config.revision=1afe7c4771501eaae2dc1cbe506c4a67609ed151" -o "$work/bin/colima-fixed-v2" ./cmd/colima
codesign --force -s - "$work/bin/colima-fixed-v2"
cd "$work/lima-src"
test "$(git rev-parse HEAD)" = 2d4314e945cda21ed777fe73a078619f23fc48df
git apply --check "$patches/lima-2.1.2.patch"
git apply "$patches/lima-2.1.2.patch"
go test -p 2 ./pkg/cidata -run '^TestDiskDeviceNameFromOrder$'
go build -p 2 -ldflags="-s -w -X github.com/lima-vm/lima/v2/pkg/version.Version=v2.1.2" -o "$work/lima-fixed/bin/limactl" ./cmd/limactl
codesign -f -v --entitlements vz.entitlements -s - "$work/lima-fixed/bin/limactl"
# The unmodified 2.1.2 companion driver and guest agent are pinned copies.
cp -Rp /opt/homebrew/Cellar/lima/2.1.2/share/lima "$work/lima-fixed/share/"
cp -Rp /opt/homebrew/Cellar/lima/2.1.2/libexec/lima "$work/lima-fixed/libexec/"
cp "$patches/colima-wrapper.sh" "$work/colima-wrapper.sh"
chmod 755 "$work/colima-wrapper.sh"
shasum -a 256 "$work/bin/colima-fixed-v2" "$work/lima-fixed/bin/limactl"
