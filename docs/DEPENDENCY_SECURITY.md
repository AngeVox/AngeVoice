# 依赖安全基线

下列漏洞范围来自 2026-09-13 的依赖审计，硬件验证更新至 2026-09-21；不是实时漏洞扫描结果。发布前必须重新审计。版本升级不代替真实模型和硬件验证，不自动关闭或忽略告警。

| 画像 | Torch / TorchAudio | CUDA | Transformers | 说明 |
| --- | --- | --- | --- | --- |
| CPU、轻量 CI | 2.13.0 / 2.11.0（CI不安装音频包） | CPU | 5.10.4 | CPU音频读写配套 TorchCodec 0.13.0 与共享 FFmpeg 库 |
| GPU | 2.6.0 / 2.6.0 | 12.4 | 5.11.0 | 使用官方 cu124；5.11.0 修复旧 Torch 导入时误用可选 FP8 类型的问题，硬件验收见下文 |
| legacy-gpu | 2.6.0 / 2.6.0 | 11.8 | 5.11.0 | 保留旧 GPU 画像；不因兼容问题回退安全基线或伪造 Torch FP8 属性 |

CPU 组合不再命中上述审计当时已报告的版本范围。两个GPU画像消除Torch反序列化critical告警，但保留以下上游风险；这是兼容性限制，不能描述为GPU无漏洞。原依赖源码安装下限提高为Torch/TorchAudio 2.6，CPU安全部署应使用上述锁定组合，不依赖宽泛下限自动选择画像。

| 告警 GHSA | 风险 | CPU 2.13 | GPU 2.6 |
| --- | --- | --- | --- |
| 53q9-r3pm-6pq6 | critical：weights_only反序列化 | 已越过受影响范围 | 已越过受影响范围 |
| rrmf-rvhw-rf47 | low：jit.script内存破坏 | 已越过受影响范围 | 保留 |
| qfhq-4f3w-5fph | low：lstm_cell内存破坏 | 已越过受影响范围 | 保留 |
| vgrw-7cvw-pwgx | moderate：unpack_sequence内存破坏 | 已越过受影响范围 | 保留 |
| x3gm-94wq-g975 | low：Quantized Sigmoid初始化 | 已越过公告受影响范围 | 保留；公告无修复版本 |
| f4hp-rmr7-r7v8 | moderate：pad_packed_sequence内存消耗 | 已越过公告受影响范围 | 保留；公告无修复版本 |
| c678-jfcj-6jmf | low：tuple handler内存破坏 | 已越过公告受影响范围 | 保留；公告无修复版本 |
| 887c-mr87-cxwp | moderate：资源释放 | 已越过受影响范围 | 保留 |
| 3749-ghw9-m3mg | low：本地拒绝服务 | 已越过受影响范围 | 保留 |
| xrqw-3rrv-vx5w | high：Transformers保存模板路径穿越 | 5.10.4 | 5.11.0，保留 5.10.4 安全下限 |

依赖告警可能只覆盖测试输入文件；其自动关闭不表示 GPU 残余消失。不要对GPU残余执行dismiss。对无明确修复版本的条目，仅声明不再命中公告列出的版本范围。

模型加载仍必须使用可信来源及既有资产完整性校验；vendor中显式weights_only=False的调用并不会因Torch升级变为安全反序列化。

资料：[PyTorch官方版本矩阵](https://pytorch.org/get-started/previous-versions/)、[TorchAudio安装说明](https://docs.pytorch.org/audio/main/installation.html)、[GitHub依赖告警](https://github.com/AngeVox/AngeVoice/security/dependabot)。

## setuptools 与分词依赖限制

镜像安装清单扫描另命中 setuptools 的 GHSA-h35f-9h28-mq5c（CVE-2026-59890，修复版83.0.0）。该问题涉及macOS上生成sdist时Unicode文件名绕过排除规则；Linux 容器运行 HTTP 服务并非该触发场景，但版本告警仍保留。

现有jieba 0.42.1的 `_compat.py` 仍调用 `pkg_resources.resource_stream`，这是保留 `setuptools<81` 的实际兼容约束。不能直接解除上限并让参考文本处理在运行时失败；后续需验证上游替代包或兼容迁移，再提升setuptools。该条由 AV-D021 继续跟踪，不忽略或误报已修复。



## 2026-09-21 Tesla P4 候选镜像实测

GPU 使用 `12.4.1-cudnn-runtime-ubuntu22.04` 基础镜像。Transformers 5.11.0 包含[上游修复 #46393](https://github.com/huggingface/transformers/pull/46393)，避免在 Torch 2.6 上访问不存在的可选 FP8 类型。CPU 约束为 5.10.4，项目允许范围 `<5.12` 容纳两套锁定组合。

在 Tesla P4（驱动 580.142，8 GB）上，两套完整候选镜像均构建成功，构建阶段 Kokoro/ZipVoice/MOSS 导入、pip check 和 WAV 读写/重采样通过。标准 GPU 实际 Torch/TorchAudio 2.6.0+cu124、ORT GPU 1.20.2；legacy 为 2.6.0+cu118、ORT GPU 1.20.1，二者 Transformers 均为 5.11.0。

直接使用新镜像内源码和依赖，独立容器、复制权重、禁网，真实隔离 worker 的 Kokoro/MOSS/ZipVoice HTTP 与 WS 全部生成有效音频；MOSS 实际 provider=cuda、ZipVoice=cuda_pytorch，关闭自动 CPU fallback。Kokoro/MOSS 额外通过 raw/prepared、收到音频后取消及后续请求恢复。标准 GPU 在这台 P4 上可运行，不要求仅因卡型切换 legacy；legacy 默认 MOSS CPU 策略不变，CUDA 验证使用显式配置。

这些是 ASGI 路由和真实模型 smoke，未涵盖所有宿主驱动、P40/V100、外部 TCP/代理部署、长期压力及主观音质/品牌读音。上表 GPU 安全残余仍开放，不能称为无漏洞。该验证对应 `91062e1` 所含 GPU 兼容修复，不代表 v2.6.616 发行镜像或后续源码候选已通过相同验证。


2026-09-23 针对本地未提交候选，分别在上述标准 GPU 与 legacy-gpu 依赖镜像中挂载当前源码，使用复制模型资产、禁网与真实隔离 worker，在 Tesla P4 上验证 ZipVoice 收到首个 WS 音频片段后发送取消，两套画像均收到 `cancelled`，随后 HTTP 请求均生成有效 WAV。标准画像 Torch 2.6.0+cu124，legacy 为 2.6.0+cu118。此结果验证的是“既有镜像依赖 + 当前挂载源码”组合，不是重新构建后的完整发行镜像，也不覆盖外部 TCP/代理、持续压力或听感。独立探针和结果见仓库外 `angevoice-repository-audit` 证据包。
