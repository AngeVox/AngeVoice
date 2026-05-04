# v2.4 功能补全计划与使用说明

v2.4 目标是在 v2.3 服务版基础上继续补齐产品化能力，同时保持默认部署轻量、稳定、可调试。

## 已纳入本轮的低风险改进

### Docker Compose 调试模板

CPU/GPU 两套 `docker-compose.yml` 都补充了完整注释，包含：

- 模型目录挂载
- `src` 源码热更新挂载
- voices 可写挂载
- workers / 并发 / 超时
- 缓存开关
- `/stats` 和 `/requests` 开关
- batch/admin/upload/mp3 预留变量
- CORS 配置说明
- 老显卡/保守兼容建议

测试环境想要 `git pull + restart` 生效，可取消注释：

```yaml
- ../../src:/app/src:ro
```

如果开启音色上传，需要取消注释：

```yaml
- ../../models/voices:/app/models/voices:rw
```

并设置：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_API_KEY=change-me
```

## 计划补齐的服务端功能

以下功能已设计好接口，但本轮大范围 `server.py` 改动被平台安全层拦截，建议拆成更小 PR 继续实现。

### 1. WebSocket cancel / stop

目标：客户端在流式合成过程中发送：

```json
{"type":"cancel"}
```

或：

```json
{"type":"stop"}
```

服务端应尽快停止后续段落生成，并在 `/requests` 里记录 `cancelled` 状态。

注意：如果当前段落已经进入同步模型推理，无法硬中断该段，只能在段落完成后停止后续段。

### 2. 批量合成 ZIP

建议接口：

```http
POST /v1/audio/batch
```

请求体：

```json
{
  "voice": "zm_010",
  "speed": 1.0,
  "response_format": "wav",
  "items": [
    {"text": "第一段", "filename": "001"},
    {"text": "第二段", "filename": "002", "voice": "zf_001"}
  ]
}
```

返回：`application/zip`，包含每条音频和 `manifest.json`。

### 3. 管理接口

建议默认关闭，通过环境变量开启：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=change-me
```

建议接口：

- `DELETE /admin/cache`：清理内存缓存
- `GET /admin/voices`：查看音色目录与音色列表
- `POST /admin/voices/upload`：上传 `.pt` 音色文件

安全建议：公网部署必须设置 `KOKORO_API_KEY`，不要裸开管理接口。

### 4. MP3 可选转码

建议默认关闭：

```bash
KOKORO_MP3_ENABLED=false
```

开启前需要镜像或宿主环境安装 `ffmpeg`。开启后：

```json
{"response_format":"mp3"}
```

返回 `audio/mpeg`。

由于 MP3 转码依赖外部二进制，建议作为可选能力，不放入默认路径。

### 5. 多引擎插件化预留

建议保留 Kokoro 作为默认引擎，后续再用插件方式接入：

- MOSS-TTS-Nano
- CosyVoice
- GPT-SoVITS

不建议直接把重依赖写入默认安装依赖，避免破坏轻量部署体验。

## 推荐版本策略

- `v2.3.x`：稳定服务版，适合默认部署
- `v2.4.0-rc1`：文档/部署模板先行，逐步补批量、管理和上传功能
- `v2.5.0`：多引擎插件化或完整 WebUI 管理能力
