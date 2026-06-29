#!/usr/bin/env bash
# 从单一 Compose 文件构建 AngeVoice fnOS/FPK 包，并校验 profile 路由。
# 包版本来自 pyproject.toml；运行镜像固定使用同版本标签。
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
RELEASE_TAG="${GITHUB_REF_NAME:-v${VERSION}}"
if [[ "$RELEASE_TAG" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-.].*)?$ ]]; then
  IMAGE_TAG="$RELEASE_TAG"
else
  IMAGE_TAG="v${VERSION}"
fi
OUT="${1:-$ROOT/dist/AngeVoice_v${VERSION}.fpk}"
mkdir -p "$(dirname "$OUT")"
[[ -f "$PKG/manifest" && -f "$PKG/LICENSE" && -f "$PKG/NOTICE" && -f "$PKG/app/docker/docker-compose.yaml" && -f "$PKG/app/docker/angevoice.env" ]] || {
  echo "fnOS 打包目录不完整" >&2
  exit 1
}
VERSION="$VERSION" IMAGE_TAG="$IMAGE_TAG" python3 - "$PKG" <<'PYVALIDATE'
import json, os, sys
from pathlib import Path
p = Path(sys.argv[1])
version = os.environ['VERSION']
image_tag = os.environ['IMAGE_TAG']
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
    ('cpu', 'angevoice-cpu', 'maxblack777/angevoice-cpu:'),
    ('gpu', 'angevoice-gpu', 'maxblack777/angevoice-gpu:'),
    ('legacy-gpu', 'angevoice-legacy-gpu', 'maxblack777/angevoice-legacy-gpu:'),
):
    assert f'  {service}:' in compose
    assert f'profiles: ["{profile}"]' in compose
    assert image in compose
assert compose.count('profiles:') == 3
for item in ('${TRIM_PKGVAR}/credentials:/app/credentials', '${TRIM_PKGVAR}/config:/app/config', '${TRIM_PKGVAR}/prompts:/app/prompts'):
    assert compose.count(item) == 3, item
for item in ('KOKORO_PROCESS_ISOLATION_ENABLED: "true"', 'MOSS_PROCESS_ISOLATION_ENABLED: "true"', 'ZIPVOICE_PROCESS_ISOLATION_ENABLED: "true"', 'ANGEVOICE_STARTUP_PRELOAD_ENABLED: "false"'):
    assert compose.count(item) == 3, item
fnos_env = (p / 'app/docker/angevoice.env').read_text(encoding='utf-8')
for item in ('ANGEVOICE_FFMPEG_ENABLED=false', 'ANGEVOICE_FFMPEG_BINARY=ffmpeg', 'ANGEVOICE_FFMPEG_TIMEOUT_SECONDS=30', 'ANGEVOICE_AUDIO_MP3_BITRATE=192k', 'ANGEVOICE_AUDIO_OPUS_BITRATE=32k', 'ANGEVOICE_AUDIO_AAC_BITRATE=96k'):
    assert item in fnos_env, item
assert 'ANGEVOICE_DEPLOYMENT_PROFILE: "gpu"' in compose
assert 'MOSS_EXECUTION_PROVIDER: "cuda"' in compose
assert 'ZIPVOICE_EXECUTION_PROVIDER: "cuda"' in compose
assert 'NVIDIA_VISIBLE_DEVICES: "all"' in compose
assert 'wizard_http_port' in compose and 'wizard_admin_password' in compose
assert 'wizard_ffmpeg_enabled' in compose
for name in ('install', 'config', 'upgrade'):
    wizard = json.loads((p / 'wizard' / name).read_text(encoding='utf-8'))
    assert 'wizard_ffmpeg_enabled' in json.dumps(wizard, ensure_ascii=False)
for name in ('install_callback', 'config_callback', 'upgrade_callback'):
    callback = (p / 'cmd' / name).read_text(encoding='utf-8')
    assert 'COMPOSE_PROFILES' in callback
    assert 'wizard_run_mode' not in callback
PYVALIDATE
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/root"
cp -a "$PKG/app" "$STAGE/app"
IMAGE_TAG="$IMAGE_TAG" python3 - "$STAGE/app/docker/docker-compose.yaml" <<'PYCOMPOSE'
import os, re, sys
from pathlib import Path
compose = Path(sys.argv[1])
image_tag = os.environ['IMAGE_TAG']
text = compose.read_text(encoding='utf-8')
text, count = re.subn(
    r'(maxblack777/angevoice-(?:cpu|gpu|legacy-gpu):)[^\s"\']+',
    rf'\1{image_tag}',
    text,
)
if count != 3:
    raise SystemExit(f'expected to normalize 3 AngeVoice images, got {count}')
compose.write_text(text, encoding='utf-8')
PYCOMPOSE
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -czf "$STAGE/root/app.tgz" -C "$STAGE/app" .
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
python3 "$ROOT/scripts/validate_fnos_package_images.py" "$OUT" --no-remote >/dev/null
echo "已构建 AngeVoice v${VERSION} fnOS/FPK 包：$OUT"
echo "打包约束：单一 Compose 文件 + COMPOSE_PROFILES 路由 cpu/gpu/legacy-gpu 服务，镜像固定到 ${IMAGE_TAG} 标签。"
