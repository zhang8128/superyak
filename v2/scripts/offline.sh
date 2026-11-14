#!/bin/sh
# Builders have no network. This points cargo at crates the lead vendored on this machine, outside the
# repository, so a fresh worktree builds offline. Run it once from the repository root: sh v2/scripts/offline.sh
# It writes only v2/.cargo/config.toml, which git ignores.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
vendor=${SUPERYAK_V2_VENDOR:-"$HOME/.superyak/v2/vendor"}
if [ ! -d "$vendor" ]; then
  echo "no vendored crates at $vendor: ask the lead to run cargo vendor there" >&2
  exit 1
fi
mkdir -p "$here/.cargo"
cat > "$here/.cargo/config.toml" <<CONFIG
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "$vendor"

[net]
offline = true
CONFIG
echo "cargo is offline, using $vendor"
echo "put cargo on PATH with: export PATH=\"\$HOME/.cargo/bin:\$PATH\""
