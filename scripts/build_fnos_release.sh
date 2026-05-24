#!/usr/bin/env bash
# Build the AngeVoice fnOS/FPK package from the single-service template.
# The package version comes from pyproject.toml; runtime image defaults use :latest.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$ROOT/packaging/fnos/AngeVoice"
VERSION="$(ROOT_PATH="$ROOT" python3 - <<'PYV'
import os, tomllib
from pathlib import Path
root = Path(os.environ['ROOT_PATH'])
print(tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version'])
PYV
)"
OUT="${1:-$ROOT/dist/AngeVoice_v${VERSION}.fpk}"
mkdir -p "$(dirname "$OUT")"
[[ -f "$PKG/manifest" && -f "$PKG/app/docker/docker-compose.yaml" && -f "$PKG/app/docker/.env" ]] || {
  echo "fnOS packaging tree incomplete" >&2
  exit 1
}
python3 - "$PKG" <<'PYVALIDATE'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
for name in ('install', 'config', 'upgrade', 'uninstall'):
    data = json.loads((p / 'wizard' / name).read_text(encoding='utf-8'))
    text = json.dumps(data, ensure_ascii=False)
    if name in {'install', 'config', 'upgrade'}:
        assert 'wizard_run_mode' in text and 'COMPOSE_PROFILES' not in text
json.loads((p / 'config/resource').read_text(encoding='utf-8'))
json.loads((p / 'config/privilege').read_text(encoding='utf-8'))
compose = (p / 'app/docker/docker-compose.yaml').read_text(encoding='utf-8')
assert compose.count('\n  angevoice:\n') == 1
assert 'profiles:' not in compose and 'COMPOSE_PROFILES' not in compose
assert '${ANGEVOICE_FNOS_IMAGE:-ghcr.io/ang77712829/angevoice-cpu:latest}' in compose
for item in ('${TRIM_PKGVAR}/credentials:/app/credentials', '${TRIM_PKGVAR}/config:/app/config', '${TRIM_PKGVAR}/prompts:/app/prompts'):
    assert item in compose, item
mode = (p / 'cmd/_mode_env.sh').read_text(encoding='utf-8')
for item in ('angevoice-cpu:latest', 'angevoice-gpu:latest', 'angevoice-legacy-gpu:latest'):
    assert item in mode, item
PYVALIDATE
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/root"
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -czf "$STAGE/root/app.tgz" -C "$PKG/app" .
APP_MD5="$(md5sum "$STAGE/root/app.tgz" | awk '{print $1}')"
python3 - "$PKG/manifest" "$STAGE/root/manifest" "$VERSION" "$APP_MD5" <<'PYMANIFEST'
from pathlib import Path
import re, sys
src, out, version, checksum = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
text = src.read_text(encoding='utf-8')
text = re.sub(r'^version\s*=.*$', f'version                       = {version}', text, flags=re.M)
text = re.sub(r'^checksum\s*=.*$', f'checksum                   = {checksum}', text, flags=re.M)
out.write_text(text, encoding='utf-8')
PYMANIFEST
for item in ICON.PNG ICON_256.PNG LICENSE cmd config wizard; do
  cp -a "$PKG/$item" "$STAGE/root/"
done
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -czf "$OUT" -C "$STAGE/root" .
tar -tzf "$OUT" > "$OUT.contents.txt"
sha256sum "$OUT" > "$OUT.sha256"
echo "Built AngeVoice v${VERSION} fnOS/FPK package: $OUT"
echo "Packaging contract: single service + wizard_run_mode variable routing (no COMPOSE_PROFILES)."
