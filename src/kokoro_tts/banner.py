"""AngeVoice 启动横幅。"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from . import __version__
from .kokoro_assets import default_moss_model_dir


_LOGO = r"""
    ___                       __     __    _          
   /   |  ____  ____ ____     \ \   / /__ (_)_______  
  / /| | / __ \/ __ `/ _ \     \ \ / / _ \/ / ___/ _ \ 
 / ___ |/ / / / /_/ /  __/      \ V /  __/ / /__/  __/ 
/_/  |_/_/ /_/\__, /\___/        \_/\___/_/\___/\___/  
             /____/                                      
""".strip("\n")


def _safe(value) -> str:
    text = str(value or "-")
    return text if text else "-"


def format_startup_banner(config) -> str:
    """生成服务启动时打印的项目信息。"""

    model_dir = Path(getattr(config, "model_dir", "") or "-")
    _moss_cfg = getattr(config, "moss_model_dir", None)
    moss_model_dir = Path(_moss_cfg) if _moss_cfg else default_moss_model_dir()
    lines = [
        _LOGO,
        "",
        f">> Version      : v{__version__}",
        ">> Maintainer   : 安歌 <https://github.com/ang77712829>",
        ">> Source       : https://github.com/ang77712829/AngeVoice",
        "-" * 72,
        f">> Python       : {platform.python_version()}",
        f">> Listen       : {_safe(getattr(config, 'host', '-'))}:{_safe(getattr(config, 'port', '-'))}",
        f">> DefaultModel : {_safe(getattr(config, 'default_model', '-'))}",
        f">> Enabled      : {','.join(getattr(config, 'enabled_models', []) or [])}",
        f">> ModelsRoot   : {_safe(os.environ.get('ANGEVOICE_MODELS_ROOT', '/app/models'))}",
        f">> KokoroDir    : {_safe(model_dir)}",
        f">> MossDir      : {_safe(moss_model_dir)}",
        "-" * 72,
    ]
    return "\n".join(lines)
