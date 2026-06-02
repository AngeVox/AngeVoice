#!/usr/bin/env bash
# 从单一 Compose 文件构建 AngeVoice fnOS/FPK 包，并校验 profile 路由。
# 包版本来自 pyproject.toml；运行镜像固定使用 :latest。
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
[[ -f "$PKG/manifest" && -f "$PKG/LICENSE" && -f "$PKG/NOTICE" && -f "$PKG/app/docker/docker-compose.yaml" && -f "$PKG/app/docker/angevoice.env" ]] || {
  echo "fnOS 打包目录不完整" >&2
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
        assert 'COMPOSE_PROFILES' in text
        assert 'wizard_run_mode' not in text
        assert 'wizard_container_runtime' not in text
json.loads((p / 'config/resource').read_text(encoding='utf-8'))
json.loads((p / 'config/privilege').read_text(encoding='utf-8'))
compose = (p / 'app/docker/docker-compose.yaml').read_text(encoding='utf-8')
for profile, service, image in (
    ('cpu', 'angevoice-cpu', 'maxblack777/angevoice-cpu:latest'),
    ('gpu', 'angevoice-gpu', 'maxblack777/angevoice-gpu:latest'),
    ('legacy-gpu', 'angevoice-legacy-gpu', 'maxblack777/angevoice-legacy-gpu:latest'),
):
    assert f'  {service}:' in compose
    assert f'profiles: ["{profile}"]' in compose
    assert image in compose
assert compose.count('profiles:') == 3
assert ':2.6.' not in compose
for item in ('${TRIM_PKGVAR}/credentials:/app/credentials', '${TRIM_PKGVAR}/config:/app/config', '${TRIM_PKGVAR}/prompts:/app/prompts'):
    assert compose.count(item) == 3, item
for item in ('KOKORO_PROCESS_ISOLATION_ENABLED: "true"', 'MOSS_PROCESS_ISOLATION_ENABLED: "true"', 'ZIPVOICE_PROCESS_ISOLATION_ENABLED: "true"', 'ANGEVOICE_STARTUP_PRELOAD_ENABLED: "false"'):
    assert compose.count(item) == 3, item
assert 'ANGEVOICE_DEPLOYMENT_PROFILE: "gpu"' in compose
assert 'MOSS_EXECUTION_PROVIDER: "cuda"' in compose
assert 'ZIPVOICE_EXECUTION_PROVIDER: "cuda"' in compose
assert 'NVIDIA_VISIBLE_DEVICES: "all"' in compose
assert 'wizard_http_port' in compose and 'wizard_admin_password' in compose
for name in ('install_callback', 'config_callback', 'upgrade_callback'):
    callback = (p / 'cmd' / name).read_text(encoding='utf-8')
    assert 'COMPOSE_PROFILES' in callback
    assert 'wizard_run_mode' not in callback
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
for item in ICON.PNG ICON_256.PNG LICENSE NOTICE cmd config wizard; do
  cp -a "$PKG/$item" "$STAGE/root/"
done
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -czf "$OUT" -C "$STAGE/root" .
tar -tzf "$OUT" > "$OUT.contents.txt"
sha256sum "$OUT" > "$OUT.sha256"
echo "已构建 AngeVoice v${VERSION} fnOS/FPK 包：$OUT"
echo "打包约束：单一 Compose 文件 + COMPOSE_PROFILES 路由 cpu/gpu/legacy-gpu 服务，镜像固定 :latest。"
