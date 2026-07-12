from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "recording.js"


def _node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_recording_wav_encoder_writes_pcm16_mono_header_and_clamps_samples() -> None:
    result = _node(
        f"""
        import {{ encodeRecordedWav }} from {json.dumps(MODULE.as_uri())};
        const blob = encodeRecordedWav([new Float32Array([-1.5, -0.5, 0, 0.5, 1.5])], 8000);
        const bytes = new Uint8Array(await blob.arrayBuffer());
        const view = new DataView(bytes.buffer);
        const ascii = (start, length) => String.fromCharCode(...bytes.slice(start, start + length));
        console.log(JSON.stringify({{
          type: blob.type,
          size: blob.size,
          riff: ascii(0, 4),
          wave: ascii(8, 4),
          format: view.getUint16(20, true),
          channels: view.getUint16(22, true),
          sampleRate: view.getUint32(24, true),
          bits: view.getUint16(34, true),
          dataBytes: view.getUint32(40, true),
          samples: Array.from({{ length: 5 }}, (_, index) => view.getInt16(44 + index * 2, true)),
        }}));
        """
    )
    assert result == {
        "type": "audio/wav",
        "size": 54,
        "riff": "RIFF",
        "wave": "WAVE",
        "format": 1,
        "channels": 1,
        "sampleRate": 8000,
        "bits": 16,
        "dataBytes": 10,
        "samples": [-32768, -16384, 0, 16383, 32767],
    }


def test_recording_controller_owns_start_stop_file_transfer_and_cleanup() -> None:
    result = _node(
        f"""
        import {{ createReferenceRecorderController }} from {json.dumps(MODULE.as_uri())};
        const events = [];
        const nodes = [];
        const track = {{ stops: 0, stop() {{ this.stops += 1; }} }};
        const stream = {{ getTracks: () => [track] }};
        const makeNode = kind => {{
          const node = {{ kind, connects: 0, disconnects: 0, connect() {{ this.connects += 1; }}, disconnect() {{ this.disconnects += 1; }} }};
          nodes.push(node);
          return node;
        }};
        let processor;
        class FakeContext {{
          constructor() {{ this.sampleRate = 10; this.destination = {{}}; this.closes = 0; }}
          createMediaStreamSource() {{ return makeNode('source'); }}
          createScriptProcessor() {{ processor = makeNode('processor'); return processor; }}
          createGain() {{ const node = makeNode('gain'); node.gain = {{ value: 1 }}; return node; }}
          async close() {{ this.closes += 1; }}
        }}
        class FakeFile {{
          constructor(parts, name, options) {{ Object.assign(this, options, {{ parts, name }}); }}
        }}
        class FakeTransfer {{
          constructor() {{
            this.files = [];
            this.items = {{ add: file => this.files.push(file) }};
          }}
        }}
        const startButton = {{ disabled: false }};
        const stopButton = {{ disabled: true }};
        const fileInput = {{ files: [] }};
        const files = [];
        const controller = createReferenceRecorderController({{
          elements: {{ startButton, stopButton, fileInput }},
          environment: {{
            isSecureContext: () => true,
            getUserMedia: async constraints => {{ events.push(['constraints', constraints]); return stream; }},
            AudioContext: FakeContext,
            Blob,
            File: FakeFile,
            DataTransfer: FakeTransfer,
            now: () => 1234,
          }},
          callbacks: {{
            supportsVoiceClone: () => true,
            supportsProfiles: () => true,
            expandProfiles: () => events.push(['expand']),
            onTemporaryReference: () => events.push(['temporary']),
            onStatus: (copy, active) => events.push(['status', copy, active]),
            onProgress: (copy, error, options) => events.push(['progress', copy, error, options]),
            onFile: file => {{ files.push(file); events.push(['file', file.name]); }},
            onLongRecording: seconds => events.push(['long', seconds]),
          }},
        }});
        const started = await controller.start();
        const activeAfterStart = controller.active;
        processor.onaudioprocess({{ inputBuffer: {{ getChannelData: () => new Float32Array(20).fill(0.25) }} }});
        const file = await controller.stop();
        console.log(JSON.stringify({{
          started,
          activeAfterStart,
          activeAfterStop: controller.active,
          startDisabledAfterStop: startButton.disabled,
          stopDisabledAfterStop: stopButton.disabled,
          trackStops: track.stops,
          nodeDisconnects: nodes.map(node => [node.kind, node.disconnects]),
          file: {{ name: file.name, type: file.type, lastModified: file.lastModified }},
          inputFileName: fileInput.files[0].name,
          eventNames: events.map(event => event[0]),
          finalStatus: events.filter(event => event[0] === 'status').at(-1),
        }}));
        """
    )
    assert result["started"] is True
    assert result["activeAfterStart"] is True
    assert result["activeAfterStop"] is False
    assert result["startDisabledAfterStop"] is False
    assert result["stopDisabledAfterStop"] is True
    assert result["trackStops"] == 1
    assert result["nodeDisconnects"] == [["source", 1], ["processor", 1], ["gain", 1]]
    assert result["file"] == {
        "name": "angevoice_reference_1234.wav",
        "type": "audio/wav",
        "lastModified": 1234,
    }
    assert result["inputFileName"] == "angevoice_reference_1234.wav"
    assert result["eventNames"].count("file") == 1
    assert result["eventNames"].count("temporary") == 1
    assert result["finalStatus"] == [
        "status",
        {"key": "studio.record.complete", "params": {"seconds": "2.0"}},
        False,
    ]


def test_recording_controller_auto_stops_at_limit_once_and_releases_resources() -> None:
    result = _node(
        f"""
        import {{ createReferenceRecorderController }} from {json.dumps(MODULE.as_uri())};
        const events = [];
        const track = {{ stops: 0, stop() {{ this.stops += 1; }} }};
        let processor;
        class FakeContext {{
          constructor() {{ this.sampleRate = 10; this.destination = {{}}; }}
          createMediaStreamSource() {{ return {{ connect() {{}}, disconnect() {{}} }}; }}
          createScriptProcessor() {{ processor = {{ connect() {{}}, disconnect() {{}}, onaudioprocess: null }}; return processor; }}
          createGain() {{ return {{ gain: {{ value: 1 }}, connect() {{}}, disconnect() {{}} }}; }}
          async close() {{ events.push(['closed']); }}
        }}
        class FakeFile {{ constructor(parts, name, options) {{ Object.assign(this, options, {{ parts, name }}); }} }}
        const controller = createReferenceRecorderController({{
          environment: {{
            isSecureContext: () => true,
            getUserMedia: async () => ({{ getTracks: () => [track] }}),
            AudioContext: FakeContext,
            Blob,
            File: FakeFile,
            DataTransfer: null,
            now: () => 9,
          }},
          callbacks: {{
            supportsVoiceClone: () => true,
            onStatus: (copy, active) => events.push(['status', copy, active]),
            onProgress: (copy, error, options) => events.push(['progress', copy, error, options]),
            onFile: file => events.push(['file', file.name]),
          }},
        }});
        await controller.start();
        processor.onaudioprocess({{ inputBuffer: {{ getChannelData: () => new Float32Array(149) }} }});
        await new Promise(resolve => setTimeout(resolve, 0));
        console.log(JSON.stringify({{
          active: controller.active,
          trackStops: track.stops,
          files: events.filter(event => event[0] === 'file'),
          progress: events.filter(event => event[0] === 'progress'),
          finalStatus: events.filter(event => event[0] === 'status').at(-1),
          closes: events.filter(event => event[0] === 'closed').length,
        }}));
        """
    )
    assert result["active"] is False
    assert result["trackStops"] == 1
    assert result["files"] == [["file", "angevoice_reference_9.wav"]]
    assert result["progress"] == [
        ["progress", {"key": "studio.record.limit_reached", "params": None}, False, {"kind": "warning"}],
        [
            "progress",
            {"key": "studio.record.limit_quality_warning", "params": None},
            False,
            {"kind": "warning"},
        ],
    ]
    assert result["finalStatus"] == [
        "status",
        {"key": "studio.record.complete_at_limit", "params": {"seconds": "14.9"}},
        False,
    ]
    assert result["closes"] == 1


def test_recording_controller_ignores_queued_audio_from_a_released_session() -> None:
    result = _node(
        f"""
        import {{ createReferenceRecorderController }} from {json.dumps(MODULE.as_uri())};
        const processors = [];
        class FakeContext {{
          constructor() {{ this.sampleRate = 10; this.destination = {{}}; }}
          createMediaStreamSource() {{ return {{ connect() {{}}, disconnect() {{}} }}; }}
          createScriptProcessor() {{
            const processor = {{ connect() {{}}, disconnect() {{}}, onaudioprocess: null }};
            processors.push(processor);
            return processor;
          }}
          createGain() {{ return {{ gain: {{ value: 1 }}, connect() {{}}, disconnect() {{}} }}; }}
          async close() {{}}
        }}
        class FakeFile {{ constructor(parts, name, options) {{ Object.assign(this, options, {{ parts, name }}); }} }}
        const files = [];
        const controller = createReferenceRecorderController({{
          environment: {{
            isSecureContext: () => true,
            getUserMedia: async () => ({{ getTracks: () => [{{ stop() {{}} }}] }}),
            AudioContext: FakeContext,
            Blob,
            File: FakeFile,
            DataTransfer: null,
            now: () => files.length,
          }},
          callbacks: {{
            supportsVoiceClone: () => true,
            onFile: file => files.push(file),
          }},
        }});
        await controller.start();
        const queuedOldCallback = processors[0].onaudioprocess;
        await controller.discard();
        await controller.start();
        queuedOldCallback({{ inputBuffer: {{ getChannelData: () => new Float32Array(20).fill(0.5) }} }});
        processors[1].onaudioprocess({{ inputBuffer: {{ getChannelData: () => new Float32Array(10).fill(0.25) }} }});
        const file = await controller.stop();
        console.log(JSON.stringify({{
          fileCount: files.length,
          wavBytes: file.parts[0].size,
        }}));
        """
    )
    assert result == {"fileCount": 1, "wavBytes": 64}


def test_recording_controller_reports_environment_failures_and_cleans_partial_stream() -> None:
    result = _node(
        f"""
        import {{ createReferenceRecorderController }} from {json.dumps(MODULE.as_uri())};
        const events = [];
        const track = {{ stops: 0, stop() {{ this.stops += 1; }} }};
        const callbacks = {{
          supportsVoiceClone: () => true,
          onStatus: copy => events.push(['status', copy.key]),
          onProgress: copy => events.push(['progress', copy.key]),
        }};
        const insecure = createReferenceRecorderController({{
          environment: {{ isSecureContext: () => false, getUserMedia: () => {{ throw new Error('must not run'); }}, AudioContext: false }},
          callbacks,
        }});
        const insecureResult = await insecure.start();
        class BrokenContext {{ constructor() {{ throw new Error('device init failed'); }} }}
        const broken = createReferenceRecorderController({{
          environment: {{
            isSecureContext: () => true,
            getUserMedia: async () => ({{ getTracks: () => [track] }}),
            AudioContext: BrokenContext,
          }},
          callbacks,
        }});
        const brokenResult = await broken.start();
        const denied = createReferenceRecorderController({{
          environment: {{
            isSecureContext: () => true,
            getUserMedia: async () => {{ const error = new Error('denied'); error.name = 'NotAllowedError'; throw error; }},
            AudioContext: BrokenContext,
          }},
          callbacks,
        }});
        const deniedResult = await denied.start();
        console.log(JSON.stringify({{ insecureResult, brokenResult, deniedResult, trackStops: track.stops, events }}));
        """
    )
    assert result["insecureResult"] is False
    assert result["brokenResult"] is False
    assert result["deniedResult"] is False
    assert result["trackStops"] == 1
    assert result["events"] == [
        ["progress", "studio.record.insecure_context"],
        ["progress", "studio.record.device_failed"],
        ["status", "studio.record.microphone_unavailable"],
        ["progress", "studio.record.permission_denied"],
        ["status", "studio.record.microphone_unavailable"],
    ]


def test_recording_module_is_importable_without_dom_and_app_only_coordinates_it() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "document" not in module
    assert "localStorage" not in module
    assert "querySelector" not in module
    assert re.findall(r"\bexport\s+(?:const|function)\s+(\w+)", module) == [
        "RECORDING_RECOMMENDED_SECONDS",
        "RECORDING_AUTO_STOP_SECONDS",
        "encodeRecordedWav",
        "createReferenceRecorderController",
    ]
    assert "import { createReferenceRecorderController } from './studio/recording.js';" in app
    assert "function encodeRecordedWav" not in app
    assert "function startReferenceRecording" not in app
    assert "function stopReferenceRecording" not in app
    assert "state.referenceRecorder" not in app
