# Release and Versioning Guide / 发布与版本指南

AngeVoice keeps package version, application version, Docker tags and Git tags aligned.

AngeVoice 需要保持 Python 包版本、FastAPI 应用版本、Docker 镜像标签和 Git tag 一致。

## Current release / 当前版本

```text
v2.4.0
```

Version sources / 版本来源：

- `pyproject.toml` → `[project].version`
- `src/kokoro_tts/__init__.py` → `__version__`
- `src/kokoro_tts/server.py` → FastAPI `version`
- Git tag → `vX.Y.Z`
- GHCR images → `ghcr.io/<owner>/angevoice-*:vX.Y.Z`

## Compatibility note / 兼容性说明

The command line executable remains:

```bash
kokoro-tts
```

This is intentional for backward compatibility. The product and service name is AngeVoice, but the historical CLI entrypoint is kept stable so existing scripts continue to work.

命令行仍保留 `kokoro-tts`，这是为了兼容旧脚本。产品名和服务名是 AngeVoice，但 CLI 入口不强制重命名。

## Pre-release checklist / 发布前检查

```bash
git checkout main
git pull
python -m pip install -e '.[dev]'
pytest -q
python - <<'PY'
import kokoro_tts
assert kokoro_tts.__version__ == '2.4.0'
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

## Creating a tag / 创建 tag

Use annotated tags so release metadata is clear:

建议使用 annotated tag：

```bash
git checkout main
git pull
git tag -a v2.4.0 -m "AngeVoice v2.4.0"
git push origin v2.4.0
```

The `Container Images` workflow builds and publishes images automatically when pushing tags matching `v*`.

推送 `v*` tag 后，`Container Images` 工作流会自动构建并发布 GHCR 镜像。

## GHCR image names / GHCR 镜像名

```text
ghcr.io/ang77712829/angevoice-cpu:v2.4.0
ghcr.io/ang77712829/angevoice-gpu:v2.4.0
ghcr.io/ang77712829/angevoice-legacy-gpu:v2.4.0
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
AngeVoice — self-hosted Chinese TTS service built on Kokoro v1.1, with OpenAI-compatible API, WebSocket streaming, Web UI, batch synthesis, and CPU/GPU/legacy-GPU Docker profiles.
```

中文描述：

```text
AngeVoice：基于 Kokoro v1.1 模型构建的中文 TTS 自托管服务，支持 OpenAI 兼容 API、WebSocket 流式播放、Web UI、批量合成和 CPU/GPU/老显卡 Docker 部署。
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
