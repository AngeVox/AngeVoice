# Model files

This directory may contain Git LFS pointer files in GitHub source archives.
Files such as `kokoro-v1_1-zh.pth` and `voices/*.pt` can be tiny pointer files,
not the real model weights.

AngeVoice detects incomplete pointer files and downloads the real Kokoro assets
from Hugging Face or ModelScope on first run, according to `ANGEVOICE_MODEL_SOURCE`.
For offline deployment, download the real model files manually before startup.


If Kokoro reports `Weights only load failed` with `Unsupported operand 118`, check whether the model or voice file starts with `version https://git-lfs.github.com/spec/v1`. That file is only a pointer. Delete it and let AngeVoice download the real asset, or run `git lfs pull`.
