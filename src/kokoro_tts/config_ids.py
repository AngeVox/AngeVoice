"""Model identifiers and normalization helpers for AngeVoice configuration."""

MODEL_FILENAME = "kokoro-v1_1-zh.pth"

PLACEHOLDER_API_KEYS = {
    "change-me",
    "change-me-to-a-real-secret-key",
    "change-me-to-a-real-secret",
    "replace-with-a-long-random-token",
    "<paste-generated-token-here>",
    "paste-generated-token-here",
    "<your-generated-secret>",
    "your-generated-secret",
    "staging-change-me-to-real-key",
}

PLACEHOLDER_ADMIN_PASSWORDS = {
    "change-me",
    "change-me-please-use-a-strong-password",
    "your-real-strong-password",
    "你的真实强密码",
    "请改为至少16位强密码",
    "<strong-password>",
    "strong-password",
}

MOSS_GENERIC_MODEL_IDS = {"moss", "moss-nano", "moss-tts-nano"}
MOSS_CPU_MODEL_IDS = {"moss-cpu", "moss-nano-cpu", "moss-tts-nano-cpu"}
MOSS_CUDA_MODEL_IDS = {"moss-cuda", "moss-gpu", "moss-nano-cuda", "moss-tts-nano-cuda"}


def normalize_config_model_id(model_id: str, moss_provider: str) -> str:
    """Normalize user-facing model aliases used by env/config files."""
    raw = str(model_id or "").strip().lower()
    if raw in MOSS_GENERIC_MODEL_IDS:
        return "moss-nano-cuda" if moss_provider == "cuda" else "moss-nano-cpu"
    if raw in MOSS_CPU_MODEL_IDS:
        return "moss-nano-cpu"
    if raw in MOSS_CUDA_MODEL_IDS:
        return "moss-nano-cuda"
    return raw
