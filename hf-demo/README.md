# AngeVoice Demo

在线演示文件夹，支持部署到 [Hugging Face Spaces](https://huggingface.co/spaces) 和 [ModelScope 魔搭](https://modelscope.cn)。

## 功能

- 🧠 双引擎切换：Kokoro v1.1 Chinese / MOSS-TTS-Nano CPU
- 🎵 20+ 中文预置音色 + MOSS 音色克隆
- ⚡ 语速调节（Kokoro）
- 💡 示例文本一键试听

## 本地运行

```bash
# 在仓库根目录
python hf-demo/app.py
```

访问 http://localhost:7860

## 部署到 Hugging Face Spaces

1. Fork 或推送代码到你的 GitHub 仓库
2. 在 [huggingface.co/new-space](https://huggingface.co/new-space) 创建 Space
3. 选择 **Docker** SDK
4. 连接到你的 GitHub 仓库
5. Spaces 会自动检测根目录的 `Dockerfile` 并构建

## 部署到 ModelScope 魔搭

> 待适配，结构已预留。ModelScope 支持 Docker 镜像部署，流程类似。

## 文件说明

```
hf-demo/
├── app.py      # Gradio 演示界面
└── README.md   # 本文件
```

根目录的 `Dockerfile` 是 HF Spaces / ModelScope 的构建文件，引用 `hf-demo/app.py`。
