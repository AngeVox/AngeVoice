"""AngeVoice Gradio Demo — Hugging Face Spaces / ModelScope 入口。

支持 Kokoro v1.1 Chinese 和 MOSS-TTS-Nano CPU 双引擎切换，
提供文本输入 → 语音合成 → 在线试听。

目录结构:
  hf-demo/
  ├── app.py          # 本文件
  └── README.md       # Space 说明

用法 (在仓库根目录执行):
  python hf-demo/app.py
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────
# app.py 在 hf-demo/ 子目录，向上找仓库根目录的 src/
_HF_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _HF_DEMO_DIR.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("angevoice-demo")

# ── 环境变量预设 ─────────────────────────────────────────────
os.environ.setdefault("ANGEVOICE_ENABLED_MODELS", "kokoro,moss-nano-cpu")
os.environ.setdefault("ANGEVOICE_DEFAULT_MODEL", "kokoro")
os.environ.setdefault("KOKORO_DEFAULT_VOICE", "zm_010")
os.environ.setdefault("MOSS_DEFAULT_VOICE", "Junhao")
os.environ.setdefault("KOKORO_WORKERS", "1")
os.environ.setdefault("KOKORO_MAX_CONCURRENT_REQUESTS", "1")
os.environ.setdefault("KOKORO_REQUEST_TIMEOUT_SECONDS", "120")
os.environ.setdefault("KOKORO_IDLE_TIMEOUT_SECONDS", "0")
os.environ.setdefault("MOSS_EXECUTION_PROVIDER", "cpu")
os.environ.setdefault("MOSS_CPU_THREADS", "2")
os.environ.setdefault("MOSS_APPLYANGEVOICE_RULES", "true")

# MOSS 需要 OpenMOSS 仓库
MOSS_REPO = _REPO_ROOT / "MOSS-TTS-Nano"
if MOSS_REPO.exists():
    os.environ.setdefault("MOSS_TTS_NANO_PATH", str(MOSS_REPO))

import gradio as gr
import numpy as np

from kokoro_tts.config import load_config
from kokoro_tts.engine import TTSEngine
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.moss_engine import MossNanoEngine

# ── 全局引擎管理 ─────────────────────────────────────────────
_cfg = load_config()
_engine_manager: EngineManager | None = None


def _get_manager() -> EngineManager:
    global _engine_manager
    if _engine_manager is None:
        kokoro_engine = TTSEngine(_cfg)
        _engine_manager = EngineManager(_cfg, initial_engine=kokoro_engine)
        logger.info("EngineManager 初始化完成 (default=%s)", _engine_manager.current_model_id)
    return _engine_manager


def _ensure_model(model_id: str):
    """确保指定模型已加载，返回引擎实例。"""
    manager = _get_manager()
    return manager.borrow(model_id).__enter__()


# ── 音色列表 ─────────────────────────────────────────────────
KOKORO_VOICES = [
    ("zm_010 (默认·女)", "zm_010"),
    ("zm_008 (女)", "zm_008"),
    ("zm_011 (女)", "zm_011"),
    ("zf_001 (女)", "zf_001"),
    ("zf_002 (女)", "zf_002"),
    ("zf_003 (女)", "zf_003"),
    ("zf_005 (女)", "zf_005"),
    ("zf_006 (女)", "zf_006"),
    ("zf_007 (女)", "zf_007"),
    ("zf_008 (女)", "zf_008"),
    ("zf_009 (女)", "zf_009"),
    ("zf_010 (女)", "zf_010"),
    ("zm_001 (男)", "zm_001"),
    ("zm_002 (男)", "zm_002"),
    ("zm_003 (男)", "zm_003"),
    ("zm_004 (男)", "zm_004"),
    ("zm_005 (男)", "zm_005"),
    ("zm_006 (男)", "zm_006"),
    ("zm_007 (男)", "zm_007"),
    ("zm_009 (男)", "zm_009"),
]

MOSS_VOICES = [
    ("Junhao (默认)", "Junhao"),
    ("male-singing", "male-singing"),
    ("female-singing", "female-singing"),
]

SAMPLE_TEXTS = [
    "大家好，欢迎体验 AngeVoice 语音合成服务！这是一个轻量级的中文 TTS 自托管方案。",
    "二零二六年五月十二日，北京天气晴朗，气温二十六摄氏度。",
    "人工智能正在改变我们的生活方式，从智能助手到自动驾驶，无处不在。",
    "春风又绿江南岸，明月何时照我还。这是一首经典的唐诗。",
    "拨打客服热线：一三八，零零零零，一二三四。工作时间：上午九点到下午五点。",
]


# ── 合成函数 ─────────────────────────────────────────────────
def _resolve_voice(display_name: str, model_name: str) -> str:
    """显示名 → 实际 voice id。"""
    table = KOKORO_VOICES if model_name == "kokoro" else MOSS_VOICES
    for label, vid in table:
        if label == display_name:
            return vid
    return KOKORO_VOICES[0][1] if model_name == "kokoro" else MOSS_VOICES[0][1]


def synthesize(text, model_name, voice_display, speed):
    """Gradio 回调：文本 → WAV 音频。"""
    if not text or not text.strip():
        raise gr.Error("请输入要合成的文本")

    text = text.strip()[:5000]
    voice = _resolve_voice(voice_display, model_name)
    t0 = time.time()

    try:
        engine = _ensure_model(model_name)
        wav_bytes = engine.synthesize(text, voice=voice, speed=speed)
    except Exception as e:
        logger.exception("合成失败")
        raise gr.Error(f"合成失败: {e}") from e

    elapsed = time.time() - t0

    import soundfile as sf
    audio_data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    return (sr, audio_data), f"✅ {model_name} | {elapsed:.2f}s | {len(audio_data)/sr:.1f}s 音频"


def update_voices(model_name: str):
    """切换引擎时更新音色下拉框。"""
    voices = KOKORO_VOICES if model_name == "kokoro" else MOSS_VOICES
    choices = [v[0] for v in voices]
    return gr.update(choices=choices, value=choices[0])


# ── Gradio UI ────────────────────────────────────────────────
THEME = gr.themes.Soft(primary_hue="orange", secondary_hue="blue")

with gr.Blocks(
    title="AngeVoice Demo",
    theme=THEME,
    css="""
    .header { text-align: center; margin-bottom: 1em; }
    .header h1 { margin-bottom: 0.2em; }
    .footer { text-align: center; font-size: 0.85em; color: #888; margin-top: 1em; }
    """,
) as demo:
    gr.Markdown(
        """
<div class="header">
<h1>🎙️ AngeVoice</h1>
<p>轻量级中文语音合成 — 支持 <b>Kokoro v1.1</b> 和 <b>MOSS-TTS-Nano</b> 双引擎</p>
</div>
""",
        elem_classes="header",
    )

    with gr.Row():
        with gr.Column(scale=3):
            text_input = gr.Textbox(
                label="📝 输入文本",
                placeholder="在这里输入中文文本，点击合成按钮生成语音...",
                lines=5,
                max_lines=10,
            )

            model_select = gr.Radio(
                label="🧠 选择引擎",
                choices=[
                    ("Kokoro v1.1 Chinese", "kokoro"),
                    ("MOSS-TTS-Nano CPU", "moss-nano-cpu"),
                ],
                value="kokoro",
                info="Kokoro 速度快，MOSS 支持音色克隆",
            )

            with gr.Row():
                voice_select = gr.Dropdown(
                    label="🎵 音色",
                    choices=[v[0] for v in KOKORO_VOICES],
                    value=KOKORO_VOICES[0][0],
                    info="切换引擎后音色列表自动更新",
                )
                speed_slider = gr.Slider(
                    label="⚡ 语速",
                    minimum=0.5,
                    maximum=2.0,
                    value=1.0,
                    step=0.1,
                    info="仅 Kokoro 引擎支持",
                )

            synthesize_btn = gr.Button("🔊 合成语音", variant="primary", size="lg")

            gr.Examples(
                examples=[[t] for t in SAMPLE_TEXTS],
                inputs=[text_input],
                label="💡 示例文本",
            )

        with gr.Column(scale=2):
            audio_output = gr.Audio(label="🎧 合成结果", type="numpy")
            status_text = gr.Markdown("*等待合成...*")

            with gr.Accordion("📊 模型信息", open=False):
                gr.Markdown(
                    """
**Kokoro v1.1 Chinese** — 82M 参数, ~312MB
- 采样率 24kHz / 单声道 · 20+ 中文预置音色 · 速度快

**MOSS-TTS-Nano CPU** — OpenMOSS ONNX
- 采样率 48kHz / 双声道 · 预置音色 + 参考音频克隆
"""
                )

    # 事件绑定
    model_select.change(fn=update_voices, inputs=[model_select], outputs=[voice_select])
    synthesize_btn.click(
        fn=synthesize,
        inputs=[text_input, model_select, voice_select, speed_slider],
        outputs=[audio_output, status_text],
    )
    text_input.submit(
        fn=synthesize,
        inputs=[text_input, model_select, voice_select, speed_slider],
        outputs=[audio_output, status_text],
    )

    gr.Markdown(
        """
<div class="footer">
🚀 <a href="https://github.com/ang77712829/AngeVoice" target="_blank">GitHub</a> ·
📦 Docker 一键部署 ·
MIT License ·
Built with ❤️ by <a href="https://github.com/ang77712829" target="_blank">安歌</a>
</div>
""",
        elem_classes="footer",
    )


# ── 启动 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("预热默认引擎 (kokoro) ...")
    try:
        _ensure_model("kokoro")
        logger.info("Kokoro 引擎预热完成")
    except Exception:
        logger.warning("Kokoro 预热失败，将在首次合成时加载", exc_info=True)

    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_api=False,
    )
