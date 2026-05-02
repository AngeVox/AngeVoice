#!/usr/bin/env python3
"""Kokoro TTS 启动脚本（兼容旧版入口）

新版推荐:
    pip install -e .
    kokoro-tts serve

旧版用法不变:
    python run-tts.py
"""

import sys
import os

# 确保包路径可用
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from kokoro_tts.cli import main

if __name__ == "__main__":
    # 兼容旧版：无参数时默认启动 serve
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    main()
