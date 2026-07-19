from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "reference-audio-preview.js"


def _node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


ELEMENT_FIXTURE = """
class FakeElement {
  constructor() {
    this.hidden = true;
    this.currentSrc = '';
    this.error = null;
    this.attrs = new Map();
    this.listeners = new Map();
    this.pauses = 0;
    this.loads = 0;
  }
  set src(value) { this.attrs.set('src', value); this.currentSrc = value; }
  get src() { return this.attrs.get('src') || ''; }
  getAttribute(name) { return this.attrs.get(name) || null; }
  removeAttribute(name) { this.attrs.delete(name); if (name === 'src') this.currentSrc = ''; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  removeEventListener(name, listener) { if (this.listeners.get(name) === listener) this.listeners.delete(name); }
  emit(name) { this.listeners.get(name)?.({ target: this }); }
  pause() { this.pauses += 1; }
  load() { this.loads += 1; }
}
"""


def test_reference_audio_identity_and_wav_response_normalization_are_portable() -> None:
    result = _node(
        f"""
        import {{
          referenceAudioUploadKey,
          referenceAudioProfileKey,
          responseAudioWavBlob,
        }} from {json.dumps(MODULE.as_uri())};
        const file = {{ name: 'voice/clip.wav', size: 42, lastModified: 99 }};
        const normalized = await responseAudioWavBlob(new Response(
          new Blob([new Uint8Array([1, 2, 3])], {{ type: 'application/octet-stream' }}),
        ));
        const existing = new Blob([new Uint8Array([4, 5])], {{ type: 'audio/wav' }});
        const preserved = await responseAudioWavBlob(new Response(existing));
        console.log(JSON.stringify({{
          uploadKey: referenceAudioUploadKey({{ engineId: ' ZipVoice ', file }}),
          emptyUploadKey: referenceAudioUploadKey({{ engineId: 'zipvoice', file: null }}),
          profileKey: referenceAudioProfileKey({{ engineId: 'ZIPVOICE', voiceId: 'voice/1', revision: 'r2' }}),
          otherEngineKey: referenceAudioProfileKey({{ engineId: 'kokoro', voiceId: 'voice/1', revision: 'r2' }}),
          normalized: {{ type: normalized.type, size: normalized.size }},
          preserved: {{ type: preserved.type, size: preserved.size }},
        }}));
        """
    )
    assert result == {
        "uploadKey": "upload:zipvoice:voice%2Fclip.wav:42:99",
        "emptyUploadKey": "",
        "profileKey": "profile:zipvoice:voice%2F1:r2",
        "otherEngineKey": "profile:kokoro:voice%2F1:r2",
        "normalized": {"type": "audio/wav", "size": 3},
        "preserved": {"type": "audio/wav", "size": 2},
    }


def test_uploaded_preview_owns_media_url_status_and_clear_lifecycle() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const element = new FakeElement();
        const created = [];
        const revoked = [];
        const progress = [];
        const durations = [];
        const controller = createReferenceAudioPreviewController({{
          element,
          requests: {{
            uploaded: async (_file, options) => {{
              if (!options.signal || options.signal.aborted) throw new Error('missing live signal');
              return new Response(new Blob([new Uint8Array([1, 2, 3])]), {{
                status: 200,
                headers: {{ 'X-AngeVoice-Duration-Seconds': '2.5' }},
              }});
            }},
          }},
          environment: {{
            URL: {{
              createObjectURL: blob => {{ const url = `blob:preview-${{blob.size}}`; created.push(url); return url; }},
              revokeObjectURL: url => revoked.push(url),
            }},
          }},
          callbacks: {{
            onProgress: (copy, error, options) => progress.push([copy, Boolean(error), options || null]),
            onDurationWarning: seconds => durations.push(seconds),
          }},
        }});
        const loaded = await controller.previewUploaded({{
          file: {{ name: 'sample.wav', size: 3, lastModified: 7 }},
          key: 'upload:sample.wav:3:7',
        }});
        const beforeLoadedData = controller.ready;
        element.emit('loadeddata');
        const afterLoadedData = controller.ready;
        const activeSource = element.src;
        controller.clear();
        console.log(JSON.stringify({{
          loaded,
          beforeLoadedData,
          afterLoadedData,
          activeSource,
          sourceAfterClear: controller.sourceKey,
          readyAfterClear: controller.ready,
          hiddenAfterClear: element.hidden,
          hasSrcAfterClear: Boolean(element.getAttribute('src')),
          pauses: element.pauses,
          loads: element.loads,
          created,
          revoked,
          progress,
          durations,
        }}));
        """
    )
    assert result == {
        "loaded": True,
        "beforeLoadedData": False,
        "afterLoadedData": True,
        "activeSource": "blob:preview-3",
        "sourceAfterClear": "",
        "readyAfterClear": False,
        "hiddenAfterClear": True,
        "hasSrcAfterClear": False,
        "pauses": 2,
        "loads": 2,
        "created": ["blob:preview-3"],
        "revoked": ["blob:preview-3"],
        "progress": [
            [
                {"key": "studio.reference_audio.preparing", "params": None},
                False,
                {"kind": "loading"},
            ],
            [{"key": "studio.reference_audio.upload_ready", "params": None}, False, None],
        ],
        "durations": [],
    }


def test_new_preview_aborts_and_rejects_late_response_from_previous_source() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const element = new FakeElement();
        const progress = [];
        const created = [];
        let resolveUpload;
        let uploadSignal;
        const uploadResponse = new Promise(resolve => {{ resolveUpload = resolve; }});
        const controller = createReferenceAudioPreviewController({{
          element,
          requests: {{
            uploaded: (_file, options) => {{ uploadSignal = options.signal; return uploadResponse; }},
            saved: async () => new Response(new Blob([new Uint8Array([9, 8])], {{ type: 'audio/wav' }})),
          }},
          environment: {{
            URL: {{
              createObjectURL: blob => {{ const url = `blob:${{blob.size}}:${{created.length}}`; created.push(url); return url; }},
              revokeObjectURL() {{}},
            }},
          }},
          callbacks: {{ onProgress: copy => progress.push(copy.key) }},
        }});
        const upload = controller.previewUploaded({{
          file: {{ name: 'old.wav', size: 4, lastModified: 1 }},
          key: 'upload:old',
        }});
        await Promise.resolve();
        const saved = controller.previewSaved({{
          voiceId: 'voice-2',
          name: 'Voice Two',
          key: 'profile:voice-2:r1',
        }});
        const savedResult = await saved;
        resolveUpload(new Response(new Blob([new Uint8Array([1, 2, 3, 4])], {{ type: 'audio/wav' }})));
        const uploadResult = await upload;
        console.log(JSON.stringify({{
          uploadResult,
          savedResult,
          uploadAborted: uploadSignal.aborted,
          sourceKey: controller.sourceKey,
          loadingKey: controller.loadingKey,
          active: controller.active,
          created,
          progress,
        }}));
        """
    )
    assert result == {
        "uploadResult": False,
        "savedResult": True,
        "uploadAborted": True,
        "sourceKey": "profile:voice-2:r1",
        "loadingKey": "",
        "active": False,
        "created": ["blob:2:0"],
        "progress": [
            "studio.reference_audio.preparing",
            "studio.reference_audio.saved_loading",
            "studio.reference_audio.saved_ready",
        ],
    }


def test_long_uploaded_preview_warns_once_and_same_source_is_not_refetched() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const progress = [];
        const warnings = [];
        let requests = 0;
        const controller = createReferenceAudioPreviewController({{
          element: new FakeElement(),
          requests: {{
            uploaded: async () => {{
              requests += 1;
              return new Response(new Blob([new Uint8Array([1])], {{ type: 'audio/wav' }}), {{
                headers: {{ 'X-AngeVoice-Duration-Seconds': '4.2' }},
              }});
            }},
          }},
          environment: {{
            URL: {{ createObjectURL: () => 'blob:long', revokeObjectURL() {{}} }},
          }},
          callbacks: {{
            onProgress: copy => progress.push(copy.key),
            onDurationWarning: seconds => warnings.push(seconds),
          }},
        }});
        const file = {{ name: 'long.wav', size: 1, lastModified: 2 }};
        const first = await controller.previewUploaded({{ file, key: 'upload:long' }});
        const duplicate = await controller.previewUploaded({{ file, key: 'upload:long' }});
        console.log(JSON.stringify({{ first, duplicate, requests, progress, warnings }}));
        """
    )
    assert result == {
        "first": True,
        "duplicate": False,
        "requests": 1,
        "progress": ["studio.reference_audio.preparing"],
        "warnings": [4.2],
    }


def test_forced_same_source_refresh_replaces_its_object_url() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const created = [];
        const revoked = [];
        let requests = 0;
        const controller = createReferenceAudioPreviewController({{
          element: new FakeElement(),
          requests: {{
            uploaded: async () => {{
              requests += 1;
              return new Response(new Blob([new Uint8Array(requests)], {{ type: 'audio/wav' }}));
            }},
          }},
          environment: {{
            URL: {{
              createObjectURL: () => {{ const url = `blob:refresh-${{created.length + 1}}`; created.push(url); return url; }},
              revokeObjectURL: url => revoked.push(url),
            }},
            setTimeout: callback => {{ callback(); return 1; }},
            clearTimeout: () => {{}},
          }},
        }});
        const file = {{ name: 'same.wav', size: 1, lastModified: 2 }};
        const key = 'upload:zipvoice:same.wav:1:2';
        const first = await controller.previewUploaded({{ file, key }});
        const forced = await controller.previewUploaded({{ file, key, force: true }});
        console.log(JSON.stringify({{ first, forced, requests, created, revoked, sourceKey: controller.sourceKey }}));
        """
    )
    assert result == {
        "first": True,
        "forced": True,
        "requests": 2,
        "created": ["blob:refresh-1", "blob:refresh-2"],
        "revoked": ["blob:refresh-1"],
        "sourceKey": "upload:zipvoice:same.wav:1:2",
    }


def test_disposed_preview_does_not_replace_media_or_report_ready_after_a_late_response() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const element = new FakeElement();
        const progress = [];
        let resolveResponse;
        const response = new Promise(resolve => {{ resolveResponse = resolve; }});
        const controller = createReferenceAudioPreviewController({{
          element,
          requests: {{ uploaded: () => response }},
          environment: {{
            URL: {{ createObjectURL: () => {{ throw new Error('must not create a URL'); }}, revokeObjectURL() {{}} }},
          }},
          callbacks: {{ onProgress: copy => progress.push(copy.key) }},
        }});
        const pending = controller.previewUploaded({{
          file: {{ name: 'late.wav', size: 1, lastModified: 1 }},
          key: 'upload:zipvoice:late.wav:1:1',
        }});
        controller.dispose();
        resolveResponse(new Response(new Blob([new Uint8Array([1])], {{ type: 'audio/wav' }})));
        const loaded = await pending;
        console.log(JSON.stringify({{
          loaded,
          sourceKey: controller.sourceKey,
          ready: controller.ready,
          active: controller.active,
          hasSrc: Boolean(element.getAttribute('src')),
          progress,
        }}));
        """
    )
    assert result == {
        "loaded": False,
        "sourceKey": "",
        "ready": False,
        "active": False,
        "hasSrc": False,
        "progress": ["studio.reference_audio.preparing"],
    }


def test_replacing_preview_retires_previous_url_without_binding_timer_to_environment() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const created = [];
        const revoked = [];
        const timers = [];
        function strictTimer(callback, milliseconds) {{
          if (this !== undefined) throw new Error('timer was called with an object receiver');
          timers.push(milliseconds);
          callback();
          return timers.length;
        }}
        const controller = createReferenceAudioPreviewController({{
          element: new FakeElement(),
          requests: {{
            saved: async voiceId => new Response(
              new Blob([new Uint8Array(voiceId === 'one' ? [1] : [2, 3])], {{ type: 'audio/wav' }}),
            ),
          }},
          environment: {{
            URL: {{
              createObjectURL: blob => {{ const url = `blob:${{blob.size}}`; created.push(url); return url; }},
              revokeObjectURL: url => revoked.push(url),
            }},
            setTimeout: strictTimer,
            clearTimeout: () => {{}},
          }},
        }});
        const first = await controller.previewSaved({{ voiceId: 'one', name: 'One', key: 'profile:one:r1' }});
        const second = await controller.previewSaved({{ voiceId: 'two', name: 'Two', key: 'profile:two:r1' }});
        console.log(JSON.stringify({{ first, second, created, revoked, timers, sourceKey: controller.sourceKey }}));
        """
    )
    assert result == {
        "first": True,
        "second": True,
        "created": ["blob:1", "blob:2"],
        "revoked": ["blob:1"],
        "timers": [150],
        "sourceKey": "profile:two:r1",
    }


def test_preview_failures_and_media_error_emit_literal_copy_descriptors() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioPreviewController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        const element = new FakeElement();
        const progress = [];
        let savedMode = 'empty-error';
        const controller = createReferenceAudioPreviewController({{
          element,
          requests: {{
            uploaded: async () => new Response('', {{ status: 422 }}),
            saved: async () => savedMode === 'empty-error'
              ? new Response('', {{ status: 500 }})
              : new Response(new Blob([new Uint8Array([7])], {{ type: 'audio/wav' }})),
            readError: async response => response.status === 422 ? 'bad wave' : '',
          }},
          environment: {{
            URL: {{ createObjectURL: () => 'blob:valid', revokeObjectURL() {{}} }},
          }},
          callbacks: {{ onProgress: (copy, error) => progress.push([copy, Boolean(error)]) }},
        }});
        const upload = await controller.previewUploaded({{
          file: {{ name: 'bad.wav', size: 0, lastModified: 0 }},
          key: 'upload:bad',
        }});
        const savedFailure = await controller.previewSaved({{
          voiceId: 'missing', name: 'Missing', key: 'profile:missing:r0'
        }});
        savedMode = 'success';
        const savedSuccess = await controller.previewSaved({{
          voiceId: 'valid', name: 'Valid', key: 'profile:valid:r1'
        }});
        element.error = {{ code: 4 }};
        element.emit('error');
        controller.dispose();
        console.log(JSON.stringify({{
          upload,
          savedFailure,
          savedSuccess,
          progress,
          listenersAfterDispose: element.listeners.size,
          hiddenAfterDispose: element.hidden,
        }}));
        """
    )
    assert result == {
        "upload": False,
        "savedFailure": False,
        "savedSuccess": True,
        "progress": [
            [{"key": "studio.reference_audio.preparing", "params": None}, False],
            [
                {
                    "key": "studio.reference_audio.upload_failed_detail",
                    "params": {"message": "bad wave"},
                },
                True,
            ],
            [
                {
                    "key": "studio.reference_audio.saved_loading",
                    "params": {"name": "Missing"},
                },
                False,
            ],
            [{"key": "studio.reference_audio.saved_failed", "params": None}, True],
            [
                {
                    "key": "studio.reference_audio.saved_loading",
                    "params": {"name": "Valid"},
                },
                False,
            ],
            [
                {
                    "key": "studio.reference_audio.saved_ready",
                    "params": {"name": "Valid"},
                },
                False,
            ],
            [
                {
                    "key": "studio.reference_audio.media_failed",
                    "params": {"code": "4"},
                },
                True,
            ],
        ],
        "listenersAfterDispose": 0,
        "hiddenAfterDispose": True,
    }


def test_reference_audio_preview_module_is_pure_and_app_only_composes_it() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "document" not in module
    assert "localStorage" not in module
    assert "querySelector" not in module
    assert re.findall(r"\bexport\s+(?:async\s+)?(?:const|function)\s+(\w+)", module) == [
        "REFERENCE_AUDIO_RECOMMENDED_SECONDS",
        "referenceAudioUploadKey",
        "referenceAudioProfileKey",
        "createReferenceAudioFileChooserController",
        "responseAudioWavBlob",
        "createReferenceAudioPreviewController",
    ]
    assert "from './studio/reference-audio-preview.js';" in app
    assert "function responseAudioWavBlob" not in app
    assert "function replaceZipVoicePreviewBlob" not in app
    assert "state.zipvoicePreview" not in app
    assert "if (!event.persisted) referenceAudioPreviewController?.dispose();" in app
    assert "referenceAudioPreviewController?.dispose()" in app
    assert "signal," in app
    assert "referenceAudioUploadKey({ engineId: profileEngineId(), file })" in app
    assert "referenceAudioProfileKey({" in app
    assert "engineId: profileEngineId()," in app


def test_reference_audio_file_chooser_projects_localized_empty_copy_without_owning_files() -> None:
    result = _node(
        f"""
        import {{ createReferenceAudioFileChooserController }} from {MODULE.as_uri()!r};
        const element = {{ textContent: '' }};
        let locale = 'zh-CN';
        const translate = key => ({{
          'zh-CN': {{ 'studio.reference_audio.no_file_selected': '未选择文件' }},
          en: {{ 'studio.reference_audio.no_file_selected': 'No file selected' }},
        }})[locale][key];
        const controller = createReferenceAudioFileChooserController({{ element, translate }});
        controller.render();
        const zhEmpty = element.textContent;
        const file = {{ name: 'reference.wav' }};
        controller.render(file);
        const zhFile = element.textContent;
        locale = 'en';
        controller.render(file);
        const enFile = element.textContent;
        controller.render(null);
        const enEmpty = element.textContent;
        locale = 'zh-CN';
        controller.render(null);
        console.log(JSON.stringify({{ zhEmpty, zhFile, enFile, enEmpty, zhAfterClear: element.textContent, sameFile: file.name === 'reference.wav' }}));
        """
    )
    assert result == {
        "zhEmpty": "未选择文件",
        "zhFile": "reference.wav",
        "enFile": "reference.wav",
        "enEmpty": "No file selected",
        "zhAfterClear": "未选择文件",
        "sameFile": True,
    }
    module = MODULE.read_text(encoding="utf-8")
    assert "createReferenceAudioFileChooserController" in module
    assert "input.files" not in module
    assert "initializeReferenceAudioFileChooser" in APP.read_text(encoding="utf-8")
