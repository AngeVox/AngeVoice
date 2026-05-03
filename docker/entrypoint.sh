#!/bin/bash
set -e

echo "📦 Installing latest source code..."
pip install --no-deps --quiet /app 2>/dev/null || pip install --no-deps /app

echo "🚀 Starting Kokoro TTS server..."
exec python3 -c "from kokoro_tts.server import run_server; run_server()"
