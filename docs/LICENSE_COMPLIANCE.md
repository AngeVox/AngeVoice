# License and Attribution Compliance

AngeVoice is released as an MIT-licensed service framework. The MIT license applies to AngeVoice project code written for this repository.

AngeVoice also integrates upstream third-party models, runtimes and assets. Those upstream components keep their own licenses and are not relicensed by AngeVoice.

## Project code

- AngeVoice framework code: MIT License
- Main license file: `../LICENSE`

## Kokoro

AngeVoice's default engine uses Kokoro / Kokoro-82M v1.1 Chinese model support.

- Upstream model: `hexgrad/Kokoro-82M-v1.1-zh`
- Upstream license: Apache License 2.0, as declared by the upstream model card or repository
- Usage in AngeVoice: default Chinese TTS engine/model integration

Kokoro model weights, voices, training data, upstream runtime components and related assets are owned by their upstream authors. AngeVoice does not relicense them under MIT.

## MOSS-TTS-Nano / OpenMOSS

AngeVoice's optional MOSS engine integrates the official OpenMOSS MOSS-TTS-Nano runtime.

- Upstream project: `OpenMOSS/MOSS-TTS-Nano`
- Upstream license: Apache License 2.0
- Upstream copyright: OpenMOSS Team, Fudan University, SII and MOSI, as stated by the upstream license file
- Usage in AngeVoice: optional CPU/CUDA MOSS-TTS-Nano engine, preset voices and reference-audio cloning

MOSS-TTS-Nano model weights, tokenizer weights, ONNX model assets, training data, official runtime code and related assets are owned by their upstream authors. AngeVoice does not relicense them under MIT.

## Docker image redistribution

The Dockerfiles may download or include OpenMOSS/MOSS-TTS-Nano runtime code during image build. When MOSS support is installed, the Dockerfiles preserve the upstream `LICENSE` file at:

```text
/app/licenses/MOSS-TTS-Nano-LICENSE
```

The Docker images also copy:

```text
/app/LICENSE
/app/THIRD_PARTY_NOTICES.md
/app/ACKNOWLEDGEMENTS.md
/app/licenses/
```

Redistributors of prebuilt images should keep these files and preserve upstream notices.

## Practical checklist before release

Before publishing a source release, wheel, Docker image or derived package:

1. Keep the AngeVoice MIT `LICENSE` file.
2. Keep `THIRD_PARTY_NOTICES.md`.
3. Keep `ACKNOWLEDGEMENTS.md`.
4. Preserve upstream license files included by downloaded or bundled upstream projects.
5. Do not describe Kokoro or MOSS-TTS-Nano weights/runtime/assets as MIT-licensed AngeVoice code.
6. Make release notes clear that AngeVoice integrates upstream Apache-2.0 Kokoro/MOSS components.

## Related files

- `../LICENSE`
- `../THIRD_PARTY_NOTICES.md`
- `../ACKNOWLEDGEMENTS.md`
- `../licenses/README.md`
