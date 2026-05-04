# Legacy GPU image

This profile is intended for older GPU environments where CUDA 12 images are inconvenient.

Recommended defaults:

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_CACHE_ENABLED=true
KOKORO_STREAM_BINARY_ENABLED=false
```

Build this profile only when the default GPU image does not work well in your environment.
