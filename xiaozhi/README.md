# AngeVoice 接入小智 ESP32 后端

这个目录只放 **AngeVoice 对小智后端的无侵入适配文件**：适配器、配置示例、一键安装脚本和教程。它不会修改小智项目的前端源码，也不会把小智项目作为子模块引入。

目标是让小智后端可以把 AngeVoice 当成本地中文 TTS 后端使用：

- Kokoro 非流式：最快跑通，最稳。
- Kokoro WebSocket 流式：日常对话推荐。
- MOSS 预设音色流式：体验 MOSS-TTS-Nano。
- MOSS 参考音频克隆：固定一段参考音频，让小智使用克隆音色说话。
- 智控台预设：提供可复制配置，不改小智前端。

## 前置条件

你需要先准备好：

1. 已部署小智 Docker 全模块，目录类似：

```text
xiaozhi-server/
├─ docker-compose_all.yml
├─ data/
│  └─ .config.yaml
└─ models/
   └─ SenseVoiceSmall/
      └─ model.pt
```

2. 已启动 AngeVoice，例如：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/scripts/install.sh)
```

3. 小智容器能访问 AngeVoice。Docker 场景下推荐使用：

```text
http://host.docker.internal:8101
ws://host.docker.internal:8101/ws/v1/tts
```

如果小智和 AngeVoice 不在同一台机器，请改成你的实际局域网 IP，例如：

```text
http://192.168.1.3:8101
ws://192.168.1.3:8101/ws/v1/tts
```

## 方式一：一键安装，推荐

在小智目录执行：

```bash
cd /path/to/xiaozhi-server
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)
```

默认安装 Kokoro 流式模式。

指定 MOSS 克隆流式：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --mode moss-clone-stream \
  --prompt-audio ./reference.wav
```

指定小智目录和 AngeVoice 地址：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --xiaozhi-dir /root/xiaozhi-server \
  --angevoice-url http://192.168.1.3:8101 \
  --angevoice-ws ws://192.168.1.3:8101/ws/v1/tts \
  --mode kokoro-stream
```

脚本会做这些事：

1. 下载 `angevoice.py`、`angevoice_stream.py`、`angevoice_clone.py` 到 `xiaozhi-server/angevoice-adapter/`。
2. 修改 `docker-compose_all.yml`，把适配器挂载到小智容器内的 `core/providers/tts/`。
3. 添加 `host.docker.internal:host-gateway`，方便小智容器访问宿主机 AngeVoice。
4. 创建 `data/angevoice_prompts/`，用于放 MOSS 克隆参考音频。
5. 可选写入 `data/.config.yaml` 示例配置。
6. 重启 `xiaozhi-esp32-server` 容器并尝试导入适配器。

## 方式二：手动安装

### 1. 复制适配器

在小智目录创建：

```bash
mkdir -p angevoice-adapter data/angevoice_prompts
```

把下面三个文件复制进去：

```text
xiaozhi/adapters/angevoice.py
xiaozhi/adapters/angevoice_stream.py
xiaozhi/adapters/angevoice_clone.py
```

### 2. 修改 docker-compose_all.yml

给 `xiaozhi-esp32-server` 服务增加挂载，参考：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"

volumes:
  - ./angevoice-adapter/angevoice.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice.py:ro
  - ./angevoice-adapter/angevoice_stream.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_stream.py:ro
  - ./angevoice-adapter/angevoice_clone.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_clone.py:ro
  - ./data/angevoice_prompts:/opt/xiaozhi-esp32-server/data/angevoice_prompts:ro
```

也可以看：`xiaozhi/examples/docker-compose.patch.example.yml`。

### 3. 重启小智 server

```bash
docker compose -f docker-compose_all.yml restart xiaozhi-esp32-server
```

### 4. 测试适配器导入

```bash
docker exec -it xiaozhi-esp32-server python - <<'PY'
from core.providers.tts import angevoice, angevoice_stream, angevoice_clone
print('AngeVoice adapters import OK')
PY
```

## 推荐模式

### 第一层：OpenAI 非流式，最快成功

适合先跑通：

```yaml
selected_module:
  TTS: AngeVoiceKokoro

TTS:
  AngeVoiceKokoro:
    type: angevoice
    api_url: http://host.docker.internal:8101
    api_key: ""
    model: kokoro
    voice: zm_010
    response_format: wav
    speed: 1.0
    output_dir: tmp/
    tts_timeout: 120
```

### 第二层：WebSocket 流式，体验提升

推荐日常对话：

```yaml
selected_module:
  TTS: AngeVoiceKokoroStream

TTS:
  AngeVoiceKokoroStream:
    type: angevoice_stream
    api_url: ws://host.docker.internal:8101/ws/v1/tts
    http_url: http://host.docker.internal:8101
    api_key: ""
    model: kokoro
    voice: zm_010
    format: pcm_s16le
    speed: 1.0
    output_dir: tmp/
    tts_timeout: 180
```

### 第三层：MOSS clone，高级玩法

先准备一段参考音频：

```text
xiaozhi-server/data/angevoice_prompts/reference.wav
```

容器内路径固定是：

```text
/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
```

配置：

```yaml
selected_module:
  TTS: AngeVoiceMossCloneStream

TTS:
  AngeVoiceMossCloneStream:
    type: angevoice_stream
    api_url: ws://host.docker.internal:8101/ws/v1/tts
    http_url: http://host.docker.internal:8101
    api_key: ""
    model: moss-nano-cpu
    voice: Junhao
    format: pcm_s16le
    prompt_audio_path: /opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
    prompt_audio_filename: reference.wav
    output_dir: tmp/
    tts_timeout: 300
```

## 如何更换 MOSS 克隆声音

只需要替换宿主机上的参考音频：

```text
xiaozhi-server/data/angevoice_prompts/reference.wav
```

建议：

- 3-10 秒清晰单人声音。
- 尽量没有背景音乐和噪声。
- 建议用 wav；mp3 也可以，但统一命名为 `reference.wav` 最省心。
- 替换后无需重新安装适配器，下一次 TTS 请求会使用新音频。

如果你要准备多个音色，可以这样放：

```text
data/angevoice_prompts/
├─ reference.wav
├─ girl.wav
├─ boy.wav
└─ narrator.wav
```

然后在智控台或 `.config.yaml` 中把 `prompt_audio_path` 改成对应容器内路径，例如：

```text
/opt/xiaozhi-esp32-server/data/angevoice_prompts/girl.wav
```

## 智控台用户注意

如果你安装的是带智控台的小智全模块，页面里的模型配置可能会覆盖 `data/.config.yaml`。

请到：

```text
智控台 → 语音合成 → 新增 / 创建副本
```

然后参考：

```text
xiaozhi/manager/presets.yaml
```

复制对应预设。

我们只提供预设配置，不修改小智前端源码，避免侵入小智项目。

## 常见问题

更多排障见：`xiaozhi/TROUBLESHOOTING.md`。
