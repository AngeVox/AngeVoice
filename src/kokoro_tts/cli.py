"""AngeVoice command line interface.

``angevoice`` is the recommended executable name. ``kokoro-tts`` remains
available for scripts created before the project was branded as AngeVoice.
"""

import argparse
import logging
import sys
from pathlib import Path


def main():
    prog = Path(sys.argv[0]).name or "angevoice"
    parser = argparse.ArgumentParser(
        prog=prog,
        description="AngeVoice — 轻量级中文 TTS 服务，基于 Kokoro v1.1 模型构建",
    )
    parser.add_argument("--version", action="version", version="AngeVoice 2.6.1")
    sub = parser.add_subparsers(dest="command", help="子命令")

    serve_p = sub.add_parser("serve", help="启动 HTTP 服务")
    serve_p.add_argument("--host", default=None, help="监听地址 (默认 0.0.0.0)")
    serve_p.add_argument("--port", type=int, default=None, help="端口 (默认 8000)")
    serve_p.add_argument("--device", choices=["auto", "cpu", "cuda"], default=None, help="推理设备")
    serve_p.add_argument("--model-dir", default=None, help="模型目录路径")
    serve_p.add_argument("--workers", type=int, default=None, help="工作进程数")

    synth_p = sub.add_parser("synth", help="合成语音到文件")
    synth_p.add_argument("text", help="要合成的文本")
    synth_p.add_argument("-o", "--output", default="output.wav", help="输出文件路径")
    synth_p.add_argument("-v", "--voice", default="zm_010", help="音色名称")
    synth_p.add_argument("-s", "--speed", type=float, default=1.0, help="语速")
    synth_p.add_argument("--device", choices=["auto", "cpu", "cuda"], default=None, help="推理设备")
    synth_p.add_argument("--model-dir", default=None, help="模型目录路径")

    voices_p = sub.add_parser("voices", help="列出可用音色")
    voices_p.add_argument("--model-dir", default=None, help="模型目录路径")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "serve":
        from .config import load_config
        from .server import run_server

        config = load_config(
            model_dir=args.model_dir,
            device=args.device,
            host=args.host,
            port=args.port,
            workers=args.workers,
        )
        run_server(config)

    elif args.command == "synth":
        from .config import load_config
        from .engine import TTSEngine

        config = load_config(model_dir=args.model_dir, device=args.device)
        engine = TTSEngine(config)
        engine.load()
        path = engine.synthesize_file(
            text=args.text,
            output_path=args.output,
            voice=args.voice,
            speed=args.speed,
        )
        print(f"✅ 音频已保存: {path}")

    elif args.command == "voices":
        from .config import load_config

        config = load_config(model_dir=args.model_dir)
        voices = config.get_voices()
        if voices:
            print(f"可用音色 ({len(voices)} 个):")
            for v in voices:
                print(f"  - {v}")
        else:
            print("⚠️ 未找到音色文件，请检查模型目录")

    else:
        parser.print_help(sys.stderr)
        parser.exit(2, "\n错误：缺少子命令。可用子命令：serve、synth、voices。\n")


if __name__ == "__main__":
    main()
