#!/bin/bash
set -e

echo "🚀 Starting Kokoro TTS server..."
exec kokoro-tts serve
