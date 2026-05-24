# 小智接入 AngeVoice 常见问题

## 1. 小智容器访问不到 AngeVoice

在宿主机测试：

```bash
curl http://127.0.0.1:8101/health
```

在小智容器里测试：

```bash
docker exec -it xiaozhi-esp32-server curl -fsS http://host.docker.internal:8101/health
```

如果失败，检查 `docker-compose_all.yml` 是否有：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

如果还是失败，改成局域网 IP：

```yaml
api_url: ws://192.168.1.3:8101/ws/v1/tts
http_url: http://192.168.1.3:8101
```

## 2. 适配器导入失败

执行：

```bash
docker exec -it xiaozhi-esp32-server python - <<'PY'
from core.providers.tts import angevoice, angevoice_stream, angevoice_clone
print('OK')
PY
```

失败时检查挂载：

```bash
docker exec -it xiaozhi-esp32-server ls -lah /opt/xiaozhi-esp32-server/core/providers/tts/angevoice*.py
```

## 3. 智控台改了配置但没生效

带智控台的小智版本可能以数据库配置为准，`data/.config.yaml` 只是兜底。请到智控台：

```text
语音合成 → 新增 / 创建副本
```

按 `xiaozhi/manager/presets.yaml` 填。

## 4. MOSS clone 没有变成新声音

先确认 AngeVoice 侧已启用 MOSS 模型：

```text
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
```

如果你使用 GPU 或 CUDA 版本，也可以是：

```text
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cuda
```

如果 AngeVoice 只启用了 `kokoro`，小智里选择 `moss-nano-cpu` / `moss-nano-cuda` 会请求失败。

确认参考音频路径：

宿主机：

```text
xiaozhi-server/data/angevoice_prompts/reference.wav
```

容器内：

```text
/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
```

检查容器内是否能看到：

```bash
docker exec -it xiaozhi-esp32-server ls -lah /opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
```

替换参考音频后，不需要重新安装适配器。下一次请求会读取新的文件。

## 5. 没声音或播放异常

优先使用：

```yaml
format: pcm_s16le
```

并确认 AngeVoice WebSocket 返回的是 PCM 流式音频。MOSS 首次加载可能比较慢，第一次请求要等模型载入。

## 6. 401 Unauthorized

如果 AngeVoice 启用了 `KOKORO_API_KEY`，小智配置里必须填：

```yaml
api_key: "你的 KOKORO_API_KEY"
```

## 7. MOSS 很慢

免费 CPU 或低配 NAS 上 MOSS clone 可能很慢。建议先用 Kokoro 流式跑通，再启用 MOSS。
