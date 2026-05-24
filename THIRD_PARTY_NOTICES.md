# Third-Party Notices

AngeVoice project code is licensed under the MIT License. See `LICENSE`.

AngeVoice integrates third-party models, runtimes and dependencies. Those components keep their own upstream licenses and are not relicensed by AngeVoice.

## Kokoro

AngeVoice uses Kokoro / Kokoro-82M v1.1 Chinese model support.

- Upstream model family: Kokoro / Kokoro-82M
- Default model: `hexgrad/Kokoro-82M-v1.1-zh`
- Upstream license: Apache License 2.0, as declared by the upstream model card or repository
- Role: default Chinese TTS engine/model integration

AngeVoice does not claim ownership of Kokoro model weights, voices, training data, upstream runtime components or upstream model assets.

## MOSS-TTS-Nano / OpenMOSS

AngeVoice integrates MOSS-TTS-Nano through the official OpenMOSS runtime code.

- Upstream project: `OpenMOSS/MOSS-TTS-Nano`
- Upstream license: Apache License 2.0
- Upstream copyright: OpenMOSS Team, Fudan University, SII and MOSI, as stated by the upstream license file
- Role: optional MOSS-TTS-Nano CPU/CUDA engine, preset voice synthesis and reference-audio cloning support

AngeVoice does not claim ownership of MOSS-TTS-Nano model weights, tokenizer weights, ONNX model assets, training data, official runtime code or other upstream OpenMOSS assets.

## Docker images

Some AngeVoice Docker images may download or include third-party runtime code and model assets during build or runtime, including OpenMOSS/MOSS-TTS-Nano runtime code and Hugging Face model files.

Redistributors of prebuilt images should preserve upstream license files and attribution notices inside the image and in accompanying documentation.

## No relicensing of upstream assets

The MIT license in this repository applies to AngeVoice project code only. It does not relicense Kokoro, MOSS-TTS-Nano, their model weights, voices, tokenizer weights, training data, upstream runtime code or any other third-party assets.

## ZipVoice / ZipVoice-Distill

AngeVoice optionally integrates the official ZipVoice inference source and downloads ZipVoice-Distill ONNX INT8 assets at runtime into the user's persistent model directory.

- Upstream project and model: `k2-fsa/ZipVoice`
- Integrated runtime role: optional zero-shot voice-cloning TTS on CPU through ONNX Runtime INT8 assets
- Upstream license: Apache License 2.0, as declared by the upstream repository/model card
- Vendored component: upstream Python inference source under `vendor/ZipVoice/` with its upstream `LICENSE`
- Runtime assets: `zipvoice_distill/text_encoder_int8.onnx`, `fm_decoder_int8.onnx`, `model.json` and `tokens.txt`

ZipVoice model assets are not relicensed by AngeVoice and are not embedded into the AngeVoice Docker image by this integration. They are downloaded into `/app/models/zipvoice/zipvoice_distill/` when the operator explicitly ensures or first uses the ZipVoice runtime.

## Vocos mel-24khz vocoder

ZipVoice synthesis uses a Vocos vocoder asset retrieved at runtime.

- Upstream model: `charactr/vocos-mel-24khz`
- Upstream license: MIT, as declared by the upstream model repository
- Runtime assets: `config.yaml` and `pytorch_model.bin`
- Persistent location: `/app/models/zipvoice/vocos-mel-24khz/`

The Vocos weights and configuration are external runtime assets and remain subject to their upstream license terms.
