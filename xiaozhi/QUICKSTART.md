# 5 分钟快速接入

## 1. 启动 AngeVoice

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/angevox/AngeVoice/main/scripts/install.sh)
```

确认能访问：

```bash
curl http://127.0.0.1:8101/health
```

## 2. 在小智目录安装适配器

```bash
cd /path/to/xiaozhi-server
bash <(curl -fsSL https://raw.githubusercontent.com/angevox/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)
```

## 3. 测试小智容器访问 AngeVoice

```bash
docker exec -it xiaozhi-esp32-server curl -fsS http://host.docker.internal:8101/health
```

## 4. 选择模式

默认是 Kokoro 流式。MOSS 克隆模式：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/angevox/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --mode moss-clone-stream \
  --prompt-audio ./reference.wav
```

ZipVoice 克隆模式：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/angevox/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --mode zipvoice-stream \
  --prompt-audio ./reference.wav \
  --prompt-text "参考音频实际朗读文本"
```

ZipVoice 要求 AngeVoice 侧启用 `zipvoice`，并且参考文本必须和参考音频实际朗读内容一致。

## 5. 智控台用户

如果你用了智控台，请在智控台里新增模型，参考：

```text
xiaozhi/manager/presets.yaml
```
