"""audio admin configuration fields."""

from __future__ import annotations

from ..fields import AdminConfigField, field_def


FIELDS: tuple[AdminConfigField, ...] = (
    field_def(
        "ffmpeg_enabled",
        "ANGEVOICE_FFMPEG_ENABLED",
        "启用 FFmpeg 转码",
        "audio",
        "bool",
        False,
        help="启用后非流式 HTTP 可输出 mp3、ogg_opus/telegram_voice、m4a；流式仍保持 pcm_s16le/wav。旧 KOKORO_MP3_ENABLED=true 会兼容视为启用。",
    ),
    field_def(
        "ffmpeg_binary",
        "ANGEVOICE_FFMPEG_BINARY",
        "FFmpeg 路径",
        "audio",
        "str",
        "ffmpeg",
        help="容器内通常保持 ffmpeg；自定义部署可填写完整可执行文件路径。",
    ),
    field_def(
        "mp3_bitrate",
        "ANGEVOICE_AUDIO_MP3_BITRATE",
        "MP3 码率",
        "audio",
        "str",
        "192k",
        help="response_format=mp3 使用，常用 128k-192k。",
    ),
    field_def(
        "audio_opus_bitrate",
        "ANGEVOICE_AUDIO_OPUS_BITRATE",
        "Opus 码率",
        "audio",
        "str",
        "32k",
        help="telegram_voice/ogg_opus 输出使用，常用 24k-48k。",
    ),
    field_def(
        "audio_aac_bitrate",
        "ANGEVOICE_AUDIO_AAC_BITRATE",
        "AAC 码率",
        "audio",
        "str",
        "96k",
        help="m4a 输出使用，常用 64k-128k。",
    ),
    field_def(
        "ffmpeg_timeout_seconds",
        "ANGEVOICE_FFMPEG_TIMEOUT_SECONDS",
        "FFmpeg 超时秒数",
        "audio",
        "float",
        30.0,
        1.0,
        3600.0,
        1.0,
        advanced=True,
    ),
)
