# Release and Versioning Guide / 发布与版本指南

AngeVoice keeps package version, application version, Docker tags and Git tags aligned.

AngeVoice 需要保持 Python 包版本、FastAPI 应用版本、Docker 镜像标签和 Git tag 一致。

## Current release / 当前版本

```text
v2.5.0
```

Version sources / 版本来源：

- `pyproject.toml` → `[project].version`
- `src/kokoro_tts/__init__.py` → `__version__`
- `src/kokoro_tts/server.py` → FastAPI `version`
- Git tag → `vX.Y.Z`
- GHCR images → `ghcr.io/<owner>/angevoice-*:vX.Y.Z`

## Compatibility note / 兼容性说明

The recommended command line executable is:

```bash
angevoice
```

The historical executable remains available for backward compatibility:

```bash
kokoro-tts
```

The product and service name is AngeVoice. Existing scripts using `kokoro-tts` should continue to work, while new documentation and examples should prefer `angevoice`.

推荐命令行为 `angevoice`。历史命令 `kokoro-tts` 继续保留，用于兼容旧脚本；新文档和示例优先使用 `angevoice`。

## Pre-release checklist / 发布前检查

```bash
git checkout main
git pull
python -m pip install -e '.[dev]'
pytest -q
python - <<'PY'
import kokoro_tts
assert kokoro_tts.__version__ == '2.5.0'
print(kokoro_tts.__version__)
PY
```

Docker smoke test / Docker 冒烟测试：

```bash
cd docker/gpu
docker compose down
docker compose up -d --build
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/v1/audio/formats
```

Optional MOSS smoke test / 可选 MOSS 冒烟测试：

```bash
docker compose up -d --build
curl http://127.0.0.1:8101/v1/models
curl -X POST http://127.0.0.1:8101/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'
curl -X POST http://127.0.0.1:8101/api/tts \
  -F model=moss-nano-cpu \
  -F text="MOSS 预设音色冒烟测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  --output moss-smoke.wav
```

For the modern GPU profile, also verify that `/v1/models` lists
`moss-nano-cuda` while `current_model` remains `kokoro` immediately after
startup. Legacy GPU should keep `moss-nano-cuda` hidden unless the release test
explicitly enables `MOSS_CUDA_ENABLED=true`.

## Creating a tag / 创建 tag

Use annotated tags so release metadata is clear:

建议使用 annotated tag：

```bash
git checkout main
git pull
git tag -a v2.5.0 -m "AngeVoice v2.5.0"
git push origin v2.5.0
```

The `Container Images` workflow builds and publishes images automatically when pushing tags matching `v*`.

推送 `v*` tag 后，`Container Images` 工作流会自动构建并发布 GHCR 镜像。

## GHCR image names / GHCR 镜像名

```text
ghcr.io/ang77712829/angevoice-cpu:v2.5.0
ghcr.io/ang77712829/angevoice-gpu:v2.5.0
ghcr.io/ang77712829/angevoice-legacy-gpu:v2.5.0
```

`latest` is published from the default branch. Version tags are published from Git tags.

`latest` 来自默认分支，版本镜像来自 Git tag。

## Repository metadata / 仓库信息建议

Suggested repository name:

```text
angevoice
```

Suggested description:

```text
AngeVoice — self-hosted Chinese TTS service built for low-power/NAS environments, with Kokoro v1.1 by default, selectable MOSS-TTS-Nano runtime, OpenAI-compatible API, WebSocket streaming, Studio Web UI, batch synthesis, and CPU/GPU/legacy-GPU Docker profiles.
```

中文描述：

```text
AngeVoice：面向低配设备与 NAS 长期运行环境的中文 TTS 自托管服务，默认基于 Kokoro v1.1，可选 MOSS-TTS-Nano 多模型运行时，支持 OpenAI 兼容 API、WebSocket 流式播放、Studio Web UI、批量合成和 CPU/GPU/老显卡 Docker 部署。
```

## Version bump checklist / 版本升级检查

When bumping to a new version, update all of these together:

升级版本时需要同步修改：

```text
pyproject.toml
src/kokoro_tts/__init__.py
src/kokoro_tts/server.py
README.md
README_EN.md
docs/RELEASE.md
```

Then run:

```bash
pytest -q
git diff --check
```
