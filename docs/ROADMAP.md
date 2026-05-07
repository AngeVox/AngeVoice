# Roadmap / 长期路线图

This roadmap tracks the long-term direction of AngeVoice. Completed items are marked with `√`; planned items are marked with `□`.

本文档用于跟踪 AngeVoice 的长期更新方向。已实现功能使用 `√` 标记，待实现功能使用 `□` 标记。

## Core TTS / 核心 TTS 能力

- √ Kokoro v1.1 Chinese model integration / Kokoro v1.1 中文模型接入
- √ Chinese pipeline with English G2P callback / 中文 pipeline + 英文 G2P 回调
- √ CLI synthesis / 命令行合成
- √ WAV output / WAV 输出
- √ PCM s16le output / PCM s16le 输出
- √ Optional MP3 output through ffmpeg / 通过 ffmpeg 可选 MP3 输出
- √ Text cleaning and length validation / 文本清理与长度校验
- √ Long text segmentation with punctuation fallback / 长文本按标点优先切分并支持兜底硬切
- √ Segment boundary smoothing / 段落边界淡入淡出与短静音处理
- √ Lightweight Chinese punctuation, time reading, segmentation, and polyphone rules / 轻量中文标点、时间读法、分词与多音字规则
- □ User-editable pronunciation dictionary / 用户可编辑发音词典
- □ SSML-like lightweight markup / 类 SSML 的轻量标记支持
- □ Per-sentence speed/pitch controls / 分句语速与音高控制

## API and service / API 与服务化

- √ OpenAI-compatible `/v1/audio/speech` / OpenAI 兼容 `/v1/audio/speech`
- √ Legacy `/api/tts` compatibility / 旧版 `/api/tts` 兼容
- √ `/v1/audio/voices` voice listing / `/v1/audio/voices` 音色列表
- √ `/v1/audio/formats` format listing / `/v1/audio/formats` 格式列表
- √ `/v1/audio/batch` batch ZIP synthesis / `/v1/audio/batch` 批量 ZIP 合成
- √ Request ID response header / 请求 ID 响应头
- √ `/health` health check / `/health` 健康检查
- √ `/stats` service metrics / `/stats` 服务统计
- √ `/requests` recent request status / `/requests` 最近请求状态
- √ In-memory LRU audio cache / 内存 LRU 音频缓存
- √ Optional generated-audio persistence / 可选生成音频持久化
- √ Request timeout control / 请求超时控制
- √ In-process concurrency guard / 进程内并发控制
- □ Persistent job queue / 持久化任务队列
- □ Background long-form audiobook jobs / 后台长文本/有声书任务
- □ Downloadable task history / 可下载任务历史
- □ Prometheus-compatible metrics / Prometheus 兼容指标

## WebSocket streaming / WebSocket 流式

- √ Segment-by-segment WebSocket streaming / 逐段 WebSocket 流式推送
- √ JSON/base64 audio frames / JSON/base64 音频帧
- √ Optional binary audio frames / 可选 binary 音频帧
- √ `cancel` / `stop` control frames / `cancel` / `stop` 控制帧
- √ Stream metadata: sample rate, channel count, format / 流式元信息：采样率、声道、格式
- √ Browser streaming playback in Studio UI / Studio UI 浏览器流式播放
- □ Standalone browser playback helper library / 独立浏览器播放辅助库
- □ Reconnect/resume strategy for long text / 长文本断线重连与续传策略
- □ True model-level streaming if upstream supports it / 上游支持后接入真正模型级流式

## Admin and voice management / 管理与音色管理

- √ Admin API switch / 管理接口开关
- √ API key guard / API Key 保护
- √ Cache clearing endpoint / 缓存清理接口
- √ Voice listing endpoint / 音色查看接口
- √ `.pt` voice upload endpoint / `.pt` 音色上传接口
- √ Writable voices mount documentation / 可写 voices 挂载说明
- □ Web UI voice upload page / Web UI 音色上传页面
- √ Voice preview and favorite voices in Studio UI / Studio UI 音色试听与收藏
- √ MOSS reference-audio clone upload in Studio UI / Studio UI 中的 MOSS 参考音频克隆上传
- □ Voice metadata database / 音色元数据数据库
- □ Role-based admin permissions / 分角色管理权限

## Web UI / 网页界面

- √ Basic Web UI / 基础 Web UI
- √ Streaming toggle and status indicator / 流式开关与状态指示
- √ Refreshed Studio UI with light/dark themes / 支持亮色与暗色主题的新版 Studio UI
- √ Collapsible service metrics cards / 可折叠服务统计卡片
- √ Built-in API Key settings for HTTP and WebSocket / 内置 HTTP 与 WebSocket API Key 设置
- √ Voice gallery filters, favorites, and recent voices / 音色库筛选、收藏与最近使用
- □ Batch synthesis page / 批量合成页面
- □ Long text/audiobook workflow / 长文本与有声书工作流
- □ Admin settings panel / 管理设置面板
- □ Realtime service dashboard / 实时服务仪表盘

## Deployment / 部署

- √ pip editable install / pip 可编辑安装
- √ CPU Docker image / CPU Docker 镜像
- √ GPU Docker image / GPU Docker 镜像
- √ Legacy GPU CUDA 11.8 image / 老显卡 CUDA 11.8 镜像
- √ Docker Compose templates / Docker Compose 模板
- √ Source hot-reload mount notes / 源码热更新挂载说明
- √ Writable voices mount notes / voices 可写挂载说明
- √ MOSS runtime preinstalled per Docker profile / MOSS runtime 按 Docker 画像预装
- √ MOSS model cache and output persistence mounts / MOSS 模型缓存与输出持久化挂载
- √ ffmpeg included in Docker images / Docker 镜像内置 ffmpeg
- √ General and conservative deployment profiles / 通用与保守部署画像
- □ Published versioned container images / 发布带版本号的容器镜像
- □ One-command install/update script / 一键安装与更新脚本
- □ Helm chart / Helm Chart
- □ systemd service example / systemd 服务示例

## Multi-engine architecture / 多引擎架构

- √ Kokoro default engine / Kokoro 默认引擎
- √ Engine interface abstraction / 引擎接口抽象
- √ Optional MOSS-TTS-Nano engine with lazy loading / 可选且按需加载的 MOSS-TTS-Nano 引擎
- √ MOSS preset voice and voice-clone modes / MOSS 预设音色与参考音频克隆模式
- √ Shared Chinese text rules for Kokoro and MOSS / Kokoro 与 MOSS 共享中文文本规则
- √ Tesla P4 CUDA probe for MOSS runtime / MOSS 运行时 Tesla P4 CUDA 探针验证
- □ Optional CosyVoice engine / 可选 CosyVoice 引擎
- □ Optional GPT-SoVITS engine / 可选 GPT-SoVITS 引擎
- √ Per-engine capability registry / 按引擎登记能力
- □ Per-engine dependency isolation / 按引擎隔离依赖

## Quality and testing / 质量与测试

- √ Unit tests for streaming helpers / 流式辅助函数单元测试
- √ Smoke test script / 冒烟测试脚本
- √ Loop stability test script / 循环稳定性测试脚本
- √ Invalid parameter tests / 非法参数测试
- √ Cache hit verification / 缓存命中验证
- □ WebSocket cancel integration test / WebSocket 取消集成测试
- □ Batch API integration test / 批量接口集成测试
- □ Admin API integration test / 管理接口集成测试
- □ CI workflow / CI 工作流
- □ Release checklist / 发布检查清单

## Documentation / 文档

- √ Chinese README / 中文 README
- √ English README / 英文 README
- √ Service profile documentation / 服务画像文档
- √ v2.5 service feature documentation / v2.5 服务功能文档
- √ Legacy GPU bilingual deployment guide / 老显卡中英双语部署说明
- √ Roadmap / 长期路线图
- □ API reference generated from OpenAPI / 基于 OpenAPI 生成 API 参考
- √ Troubleshooting cookbook / 排障手册
- □ Performance tuning guide / 性能调优指南

## Version direction / 版本方向

- √ v2.1.x: streaming and Docker stabilization / 流式与 Docker 稳定化
- √ v2.3.x: service edition with cache, stats, request tracking / 服务化版本，缓存、统计、请求追踪
- √ v2.4.x: batch, admin, optional MP3, WebSocket cancel, legacy GPU profile / 批量、管理、可选 MP3、WebSocket 取消、老显卡画像
- √ v2.5.x: service hardening, Chinese rules, Studio UI refresh, and multi-model MOSS runtime / 服务稳定性、中文规则、Studio UI 刷新与多模型 MOSS 运行时
- □ v2.6.x: Web UI management, task workflow, and more model adapters / Web UI 管理、任务工作流与更多模型适配
- □ v3.x: multi-engine plugin architecture / 多引擎插件架构
