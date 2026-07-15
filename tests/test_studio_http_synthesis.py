from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from collections import Counter


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "http-synthesis.js"
DEBT = ROOT / "tests" / "quality" / "studio_copy_debt.json"


def _node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


NODE_FIXTURE = """
class FakeFormData {
  constructor() { this.items = []; }
  append(key, value, filename) {
    const stored = value && typeof value === 'object' && 'name' in value ? `file:${value.name}` : String(value);
    this.items.push([key, stored, filename ?? null]);
  }
}
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}
function response(bytes, { status = 200, requestId = '' } = {}) {
  return new Response(new Blob([new Uint8Array(bytes)]), {
    status,
    headers: requestId ? { 'X-Request-ID': requestId } : {},
  });
}
function snapshot(overrides = {}) {
  return {
    model: 'zipvoice', text: 'hello', voice: '', speed: 1.25,
    textNormalization: 'wetext', engineParams: { steps: 8 },
    promptAudioFile: null, promptText: '', supportsVoiceClone: false,
    supportsProfiles: false, requiresPromptText: false, requiresPromptAudio: false,
    autoplay: true, ...overrides,
  };
}
"""


def test_http_controller_preserves_request_snapshot_payload_and_handoff_contract() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const calls = [];
        const busy = [];
        const progress = [];
        const ids = [];
        const blobs = [];
        let refreshes = 0;
        const pending = deferred();
        const original = snapshot({{
          engineParams: {{ steps: 8, guidance: 1.5, empty: '' }},
          promptAudioFile: {{ name: 'reference.wav' }}, promptText: 'spoken reference',
          supportsVoiceClone: true, supportsProfiles: true, requiresPromptText: true,
        }});
        const controller = createHttpSynthesisController({{
          request: (url, options) => {{ calls.push([url, options]); return pending.promise; }},
          cancelRequest: async () => null,
          readError: async () => 'unused',
          createRequestId: () => 'client-1',
          callbacks: {{
            onBusyChange: value => busy.push(value),
            onProgress: copy => progress.push(copy),
            onRequestId: value => ids.push(value),
            onBlob: (blob, metadata) => blobs.push([blob.size, metadata]),
            onRefresh: () => {{ refreshes += 1; }},
          }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const started = controller.start(original);
        original.model = 'changed-after-start';
        original.promptText = 'changed-after-start';
        original.engineParams.steps = 99;
        const [url, options] = calls[0];
        pending.resolve(response([1, 2, 3], {{ requestId: 'server-1' }}));
        const outcome = await started;
        console.log(JSON.stringify({{
          url, method: options.method, header: options.headers['X-Client-Request-ID'],
          signalLiveAtDispatch: !options.signal.aborted, form: options.body.items,
          outcome: {{ status: outcome.status, requestId: outcome.requestId, blobSize: outcome.blob.size }},
          busy, progress, ids, blobs, refreshes, active: controller.active, requestId: controller.requestId,
        }}));
        """
    )
    assert result == {
        "url": "/api/tts",
        "method": "POST",
        "header": "client-1",
        "signalLiveAtDispatch": True,
        "form": [
            ["model", "zipvoice", None],
            ["text", "hello", None],
            ["voice", "", None],
            ["speed", "1.25", None],
            ["response_format", "wav", None],
            ["text_normalization", "wetext", None],
            ["steps", "8", None],
            ["guidance", "1.5", None],
            ["prompt_audio", "file:reference.wav", "reference.wav"],
            ["prompt_text", "spoken reference", None],
        ],
        "outcome": {"status": "completed", "requestId": "server-1", "blobSize": 3},
        "busy": [True, False],
        "progress": [
            {"key": "studio.synthesis.http.generating_conditioned", "params": None},
            {"key": "studio.synthesis.http.completed", "params": None},
        ],
        "ids": ["client-1", "server-1"],
        "blobs": [[3, {"autoplay": True, "requestId": "server-1"}]],
        "refreshes": 1,
        "active": False,
        "requestId": "",
    }


def test_http_controller_preserves_saved_profile_and_temporary_reference_conditions() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const forms = [];
        let id = 0;
        const controller = createHttpSynthesisController({{
          request: async (_url, options) => {{ forms.push(options.body.items); return response([1]); }},
          cancelRequest: async () => null,
          readError: async () => 'unused',
          createRequestId: () => `client-${{++id}}`,
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const saved = await controller.start(snapshot({{
          voice: 'saved-voice', promptAudioFile: {{ name: 'ignored.wav' }}, promptText: 'ignored',
          supportsVoiceClone: true, supportsProfiles: true, requiresPromptText: true, requiresPromptAudio: true,
        }}));
        const temporary = await controller.start(snapshot({{
          voice: '', promptAudioFile: {{ name: 'temporary.wav' }}, promptText: 'reference words',
          supportsVoiceClone: true, supportsProfiles: true, requiresPromptText: true, requiresPromptAudio: true,
        }}));
        console.log(JSON.stringify({{ statuses: [saved.status, temporary.status], forms }}));
        """
    )
    assert result["statuses"] == ["completed", "completed"]
    saved = result["forms"][0]
    temporary = result["forms"][1]
    assert [item for item in saved if item[0] in {"prompt_audio", "prompt_text"}] == []
    assert [item for item in temporary if item[0] in {"prompt_audio", "prompt_text"}] == [
        ["prompt_audio", "file:temporary.wav", "temporary.wav"],
        ["prompt_text", "reference words", None],
    ]


def test_http_controller_local_validation_returns_translation_descriptors_without_requesting() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        let requests = 0;
        const progress = [];
        const controller = createHttpSynthesisController({{
          request: async () => {{ requests += 1; return response([1]); }},
          cancelRequest: async () => null,
          readError: async () => 'unused',
          createRequestId: () => 'unused',
          callbacks: {{ onProgress: (copy, error) => progress.push([copy, error]) }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const empty = await controller.start(snapshot({{ text: '   ' }}));
        const promptText = await controller.start(snapshot({{
          promptAudioFile: {{ name: 'ref.wav' }}, supportsVoiceClone: true,
          supportsProfiles: true, requiresPromptText: true, promptText: '',
        }}));
        const promptAudio = await controller.start(snapshot({{
          supportsVoiceClone: true, supportsProfiles: true, requiresPromptAudio: true,
        }}));
        console.log(JSON.stringify({{
          requests, statuses: [empty.status, promptText.status, promptAudio.status], progress,
        }}));
        """
    )
    assert result == {
        "requests": 0,
        "statuses": ["validation_error", "validation_error", "validation_error"],
        "progress": [
            [{"key": "studio.compose.text_required", "params": None}, True],
            [{"key": "studio.synthesis.http.prompt_text_required", "params": None}, True],
            [{"key": "studio.synthesis.http.reference_required", "params": None}, True],
        ],
    }


def test_http_controller_routes_401_and_non_2xx_without_changing_error_policy() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        let mode = '401';
        let readErrors = 0;
        let auth = 0;
        const errors = [];
        const blobs = [];
        const progress = [];
        let id = 0;
        const controller = createHttpSynthesisController({{
          request: async () => mode === '401' ? response([], {{ status: 401 }}) : response([], {{ status: 422 }}),
          cancelRequest: async () => null,
          readError: async response => {{ readErrors += 1; return `decoded-${{response.status}}`; }},
          createRequestId: () => `client-${{++id}}`,
          callbacks: {{
            onAuthRequired: () => {{ auth += 1; }},
            onRequestError: error => errors.push(error.message),
            onBlob: blob => blobs.push(blob.size),
            onProgress: copy => progress.push(copy.key),
          }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const unauthorized = await controller.start(snapshot());
        mode = '422';
        const rejected = await controller.start(snapshot());
        console.log(JSON.stringify({{
          statuses: [unauthorized.status, rejected.status], auth, readErrors, errors, blobs, progress,
        }}));
        """
    )
    assert result == {
        "statuses": ["auth_required", "error"],
        "auth": 1,
        "readErrors": 1,
        "errors": ["decoded-422"],
        "blobs": [],
        "progress": ["studio.synthesis.http.generating", "studio.synthesis.http.generating"],
    }


def test_http_controller_latest_start_wins_without_stale_busy_blob_progress_or_refresh() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const pending = [deferred(), deferred()];
        const signals = [];
        const cancelled = [];
        const busy = [];
        const progress = [];
        const blobs = [];
        const ids = [];
        let requests = 0;
        let refreshes = 0;
        const controller = createHttpSynthesisController({{
          request: (_url, options) => {{ signals.push(options.signal); return pending[requests++].promise; }},
          cancelRequest: async id => {{ cancelled.push(id); }},
          readError: async () => 'unused',
          createRequestId: () => `client-${{requests + 1}}`,
          callbacks: {{
            onBusyChange: value => busy.push(value), onProgress: copy => progress.push(copy.key),
            onBlob: (_blob, metadata) => blobs.push(metadata.requestId), onRequestId: id => ids.push(id),
            onRefresh: () => {{ refreshes += 1; }},
          }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const first = controller.start(snapshot({{ text: 'A' }}));
        const second = controller.start(snapshot({{ text: 'B' }}));
        pending[1].resolve(response([2], {{ requestId: 'server-B' }}));
        const secondResult = await second;
        pending[0].resolve(response([1], {{ requestId: 'server-A' }}));
        const firstResult = await first;
        await Promise.resolve();
        console.log(JSON.stringify({{
          statuses: [firstResult.status, secondResult.status], aborted: signals.map(signal => signal.aborted),
          cancelled, busy, progress, blobs, ids, refreshes, active: controller.active,
        }}));
        """
    )
    assert result == {
        "statuses": ["superseded", "completed"],
        "aborted": [True, False],
        "cancelled": ["client-1"],
        "busy": [True, True, False],
        "progress": [
            "studio.synthesis.http.generating",
            "studio.synthesis.http.generating",
            "studio.synthesis.http.completed",
        ],
        "blobs": ["server-B"],
        "ids": ["client-1", "client-2", "server-B"],
        "refreshes": 1,
        "active": False,
    }


def test_http_controller_stop_then_immediate_restart_isolates_abort_and_cancel_continuations() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const pending = [deferred(), deferred()];
        const signals = [];
        const cancelled = [];
        const busy = [];
        const progress = [];
        const blobs = [];
        let requests = 0;
        let refreshes = 0;
        const controller = createHttpSynthesisController({{
          request: (_url, options) => {{ signals.push(options.signal); return pending[requests++].promise; }},
          cancelRequest: async id => {{ cancelled.push(id); }},
          readError: async () => 'unused',
          createRequestId: () => `client-${{requests + 1}}`,
          callbacks: {{
            onBusyChange: value => busy.push(value), onProgress: copy => progress.push(copy.key),
            onBlob: (_blob, metadata) => blobs.push(metadata.requestId), onRefresh: () => {{ refreshes += 1; }},
          }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const first = controller.start(snapshot({{ text: 'A' }}));
        const stopped = controller.stop();
        const second = controller.start(snapshot({{ text: 'B' }}));
        pending[1].resolve(response([2], {{ requestId: 'server-B' }}));
        const secondResult = await second;
        pending[0].resolve(response([1], {{ requestId: 'server-A' }}));
        const firstResult = await first;
        await stopped.completion;
        console.log(JSON.stringify({{
          stopped: {{ stopped: stopped.stopped, requestId: stopped.requestId }},
          statuses: [firstResult.status, secondResult.status], aborted: signals.map(signal => signal.aborted),
          cancelled, busy, progress, blobs, refreshes, active: controller.active,
        }}));
        """
    )
    assert result == {
        "stopped": {"stopped": True, "requestId": "client-1"},
        "statuses": ["superseded", "completed"],
        "aborted": [True, False],
        "cancelled": ["client-1"],
        "busy": [True, False, True, False],
        "progress": [
            "studio.synthesis.http.generating",
            "studio.synthesis.http.generating",
            "studio.synthesis.http.completed",
        ],
        "blobs": ["server-B"],
        "refreshes": 1,
        "active": False,
    }


def test_http_controller_dispose_silences_every_late_ui_continuation() -> None:
    result = _node(
        f"""
        import {{ createHttpSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const pending = deferred();
        const events = [];
        let signal;
        const controller = createHttpSynthesisController({{
          request: (_url, options) => {{ signal = options.signal; return pending.promise; }},
          cancelRequest: async id => {{ events.push(['cancel', id]); }},
          readError: async () => 'unused',
          createRequestId: () => 'client-1',
          callbacks: {{
            onBusyChange: value => events.push(['busy', value]), onProgress: copy => events.push(['progress', copy.key]),
            onBlob: () => events.push(['blob']), onAuthRequired: () => events.push(['auth']),
            onRequestError: () => events.push(['error']), onRefresh: () => events.push(['refresh']),
          }},
          environment: {{ FormData: FakeFormData, AbortController }},
        }});
        const started = controller.start(snapshot());
        controller.dispose();
        pending.resolve(response([1], {{ requestId: 'late-server' }}));
        const outcome = await started;
        await Promise.resolve();
        console.log(JSON.stringify({{
          status: outcome.status, aborted: signal.aborted, active: controller.active,
          requestId: controller.requestId, events,
        }}));
        """
    )
    assert result == {
        "status": "superseded",
        "aborted": True,
        "active": False,
        "requestId": "",
        "events": [
            ["busy", True],
            ["progress", "studio.synthesis.http.generating"],
            ["cancel", "client-1"],
        ],
    }


def test_http_module_is_pure_esm_and_app_is_only_the_composition_player_and_error_owner() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert re.findall(r"\bexport\s+function\s+(\w+)", module) == ["createHttpSynthesisController"]
    assert "document" not in module
    assert "window" not in module
    assert "import { translate" not in module
    assert "fetch(" not in module
    assert "state." not in module
    assert "from './studio/http-synthesis.js';" in app
    assert "state.currentAbort" not in app
    assert app.count("synthesizeHttp(") == 3  # definition, submit, preview
    body = re.search(r"function synthesizeHttp\([^)]*\) \{(?P<body>.*?)\n\}", app, re.DOTALL)
    assert body
    assert "createHttpSynthesisController" in body.group("body")
    assert "new FormData" not in body.group("body")
    assert "fetch(" not in body.group("body")
    assert "onAuthRequired" in body.group("body")
    assert "state.hasCookieSession = false" in body.group("body")
    assert "state.authRejected = true" in body.group("body")
    assert "els.settingsDialog.showModal()" in body.group("body")
    assert "error.message || '生成失败'" in body.group("body")
    assert "httpSynthesisController?.stop()" in app
    assert "httpSynthesisController?.dispose()" in app


def test_http_debt_ratchet_removes_exactly_the_eight_1e_3b_fingerprints() -> None:
    registered = json.loads(DEBT.read_text(encoding="utf-8"))
    fingerprints = {
        hashlib.sha256(
            f"{item['path']}\0{item['owner']}\0{item['text']}".encode()
        ).hexdigest()[:16]
        for item in registered
    }
    removed = {
        "5d70da1b2674b384",
        "acb1f5af1ab95cab",
        "cf4768d81a9e2778",
        "bca0dc8cd7dc9539",
        "79cedc8d225de968",
        "7b3d4eb0224d608b",
        "f972f5561ba0fe26",
        "d521a12a1c9693ab",
    }
    assert len(registered) == 30
    assert fingerprints.isdisjoint(removed)
    assert Counter(item["target_phase"] for item in registered) == Counter({"1E-3C": 11, "1H": 19})
