# 新模型 Adapter 接入模板：不再堆公共特判

## 目标与硬规则

新增一个支持预置音色、参考音频或保存 Profile 的模型时，应只新增 adapter/runtime/资产/provider/schema 注册及该模型专属测试；**不得再要求修改 `routes/audio.py`、`routes/ws.py` 或为 CPU/CUDA 新建用户可见模型名**。

AngeVoice 已提供的通用入口：

```text
contracts/SynthesisRequest、VoiceCondition、GenerationParameters、SynthesisResult
contracts/StreamingRequest、StreamingResult、CancellationContext
services/SynthesisService、StreamingService、VoiceProfileService
engines/ProviderPolicy、EngineParameterSchema、EngineRegistry
resources/RuntimeResourceStatus
Studio capability 驱动的录音、上传、Profile 试听/保存/删除 UI
```

## 最小 adapter 模板

```python
from ..base import EngineCapabilities, ProviderStatus

class ExampleAdapter:
    public_id = "example"
    public_name = "Example TTS"

    def __init__(self, cfg, runtime=None, *, requested_provider="cpu", profile_store=None):
        self.cfg = cfg
        self.runtime = runtime or ExistingStableRuntime(cfg)
        self.requested_provider = requested_provider
        self.profile_store = profile_store

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            modes=("voice_clone", "saved_voice_profile"),
            voice_clone_supported=True,
            requires_prompt_audio=True,
            requires_prompt_text=True,
            supports_saved_voice_profiles=True,
            speed_supported=True,
            stream_mode="segmented",
            provider_fallback=True,
            sample_rate=24000,
            channels=1,
        )

    def metadata(self) -> dict:
        result = {"id": self.public_id, "name": self.public_name}
        result.update(self.capabilities().as_dict())
        result.update(ProviderStatus(self.requested_provider, self.actual_provider, self.fallback, self.fallback_reason).as_dict())
        return result

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0, **kwargs) -> bytes:
        return self.runtime.synthesize(text=text, voice=voice, speed=speed, **kwargs)

    def synthesize_stream(self, text: str, voice: str = "", speed: float = 1.0, fmt: str = "pcm_s16le", *, cancel_check=None, **kwargs):
        yield from self.runtime.synthesize_stream(text, voice, speed, fmt, cancel_check=cancel_check, **kwargs)
```

## 接入步骤

1. 在 `engines/adapters/` 新增 adapter；包装稳定 runtime，不把实现参数泄漏给公共路由。
2. 在 `EngineRegistry` 注册唯一 canonical ID 与稳定产品展示名。
3. 在 `ProviderPolicy` 注册 CPU/GPU/fallback 决策；Provider 变化不得形成多个 Studio 模型名。
4. 有专属生成参数时，仅在 `EngineParameterSchema` 注册字段；前端将依据 schema 动态渲染，HTTP/WS 会统一发送。
5. 支持保存参考音色时，向 `VoiceProfileService.register_store(engine_id, store, requires_reference=...)` 注册 store；需要参考录音推荐文本时，再调用 `register_recommended_prompts(engine_id, prompts)`；随后自动复用：

```text
GET/POST /v1/voice-profiles?engine=<id> 及 /v1/voice-profiles/<id>
PATCH/DELETE /v1/voice-profiles/{engine}/{voice_id}
POST /v1/reference-audio/{engine}/preview
GET /v1/voice-profiles/{engine}/{voice_id}/reference.wav
```

6. 声明 `supports_saved_voice_profiles`、`requires_prompt_audio`、`requires_prompt_text` 等 capability 后，Studio 的网页录音、上传、保存/试听/删除流程直接复用该模型，无需新增前端模型分支。
7. 实现资产状态/修复 provider，并将运行状态接入统一资源/诊断 envelope。
8. 添加 contract、provider/fallback、Profile、HTTP/WS、取消与资源测试。

## 兼容边界

旧版本的 `/v1/zipvoice/*` 及若干 `zipvoice-*` DOM/CSS 名称暂保留作兼容外壳；当前公共业务链路已经按 capability 和通用 API 执行，后续新增模型不得依赖这些兼容路径。

## 禁止的接入方式

```text
在 routes/audio.py 或 routes/ws.py 新增新模型判断作为主路径
在 ServiceState 新增某引擎私有条件解析作为主路径
为了 CPU/CUDA/provider 变化新增公开模型 ID 或改变产品名
为接入新模型重写已稳定的 Kokoro/MOSS/ZipVoice runtime
在 Studio 中按 model id 复制一套录音/Profile UI
```
