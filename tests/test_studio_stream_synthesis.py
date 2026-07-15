from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "kokoro_tts" / "static" / "studio" / "stream-synthesis.js"
APP = ROOT / "src" / "kokoro_tts" / "static" / "app.js"
DEBT = ROOT / "tests" / "quality" / "studio_copy_debt.json"


def _node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


NODE_HARNESS = r"""
class FakeSocket {
  constructor(label) {
    this.label = label;
    this.readyState = 0;
    this.sent = [];
    this.closeCount = 0;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
  }
  send(value) { this.sent.push(JSON.parse(value)); }
  close() { this.closeCount += 1; this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.({}); }
  message(value) { this.onmessage?.({ data: value }); }
  json(value) { this.message(JSON.stringify(value)); }
  fail() { this.onerror?.({ type: 'error' }); }
  serverClose(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
}

function createHarness() {
  const h = {
    sockets: [], players: [], busy: [], progress: [], outputBegins: 0,
    blobs: [], serverErrors: [], playbackErrors: [], socketErrors: 0,
    promptErrors: [], sessions: 0, refreshes: 0, states: 0,
    cancels: [], reads: [],
  };
  h.dependencies = {
    createSocket: () => {
      const socket = new FakeSocket(`socket-${h.sockets.length + 1}`);
      h.sockets.push(socket);
      return socket;
    },
    readPromptAudio: file => {
      h.reads.push(file.name);
      return Promise.resolve(`base64:${file.name}`);
    },
    cancelRequest: requestId => {
      h.cancels.push(requestId);
      return Promise.resolve({ ok: true });
    },
    createPlayer: callbacks => {
      const player = {
        label: `player-${h.players.length + 1}`,
        playing: false, hasAudio: false, underrunCount: 0,
        prebufferSeconds: 0.25, stopCount: 0, disposeCount: 0,
        chunks: [],
        setPrebuffer(value) { this.prebufferSeconds = Number(value); return this.prebufferSeconds; },
        enqueuePCM(data, sampleRate, channels) {
          this.hasAudio = true;
          this.playing = true;
          this.chunks.push({ data, sampleRate, channels });
          callbacks.onStateChange();
        },
        bufferedSeconds() { return 1.25; },
        buildWavBlob() { return this.hasAudio ? { wav: this.label, chunks: this.chunks.length } : null; },
        stop() { this.stopCount += 1; this.playing = false; },
        dispose() { this.disposeCount += 1; this.playing = false; this.hasAudio = false; },
      };
      h.players.push(player);
      return player;
    },
    callbacks: {
      onBusyChange: value => h.busy.push(value),
      onProgress: (copy, options = {}) => h.progress.push({ key: copy.key, params: copy.params, options }),
      onOutputBegin: () => { h.outputBegins += 1; },
      onBlob: (blob, options) => h.blobs.push({ blob, options }),
      onServerError: payload => h.serverErrors.push(payload),
      onPlaybackError: error => h.playbackErrors.push(String(error?.message || error)),
      onSocketError: () => { h.socketErrors += 1; },
      onPromptReadError: error => h.promptErrors.push(error.message),
      onSessionInvalid: () => { h.sessions += 1; },
      onRefresh: () => { h.refreshes += 1; },
      onStateChange: () => { h.states += 1; },
    },
  };
  return h;
}

function snapshot(overrides = {}) {
  return {
    text: 'hello', model: 'kokoro', modelId: 'kokoro', voice: 'zf_xiaobei',
    speed: 1.1, textNormalization: 'wetext', token: 'secret', engineParams: {},
    promptAudioFile: null, promptText: '', supportsVoiceClone: false,
    supportsProfiles: false, requiresPromptText: false, prebufferSeconds: 0.25,
    ...overrides,
  };
}
"""


def test_pure_esm_dependency_validation_and_lazy_construction() -> None:
    result = _node(
        f"""
        for (const name of ['window', 'document', 'WebSocket', 'FileReader']) {{
          Object.defineProperty(globalThis, name, {{
            configurable: true,
            get() {{ throw new Error(`import touched ${{name}}`); }},
          }});
        }}
        const {{ createStreamSynthesisController }} = await import({json.dumps(MODULE.as_uri())});
        {NODE_HARNESS}
        const h = createHarness();
        const controller = createStreamSynthesisController(h.dependencies);
        let validation = '';
        try {{ createStreamSynthesisController({{ ...h.dependencies, createSocket: null }}); }}
        catch (error) {{ validation = `${{error.name}}:${{error.message}}`; }}
        console.log(JSON.stringify({{
          sockets: h.sockets.length, players: h.players.length,
          active: controller.active, busy: controller.busy, disposed: controller.disposed,
          frozen: Object.isFrozen(controller), validation,
        }}));
        """
    )
    assert result == {
        "sockets": 0,
        "players": 0,
        "active": False,
        "busy": False,
        "disposed": False,
        "frozen": True,
        "validation": "TypeError:stream synthesis dependency createSocket must be a function",
    }


def test_snapshot_payload_prompt_preparation_validation_and_latest_start_wins() -> None:
    result = _node(
        f"""
        import {{ createStreamSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_HARNESS}
        const h = createHarness();
        let resolveA;
        h.dependencies.readPromptAudio = file => new Promise(resolve => {{ resolveA = resolve; }});
        const controller = createStreamSynthesisController(h.dependencies);
        const pendingA = controller.start(snapshot({{
          text: 'A', voice: '', supportsVoiceClone: true,
          promptAudioFile: {{ name: 'a.wav', type: 'audio/wav' }}, promptText: 'A prompt',
        }}));
        await Promise.resolve();

        const engineParams = {{ steps: 4 }};
        const sourceB = snapshot({{ text: 'B', engineParams }});
        const startedB = await controller.start(sourceB);
        sourceB.text = 'MUTATED';
        sourceB.token = 'changed';
        engineParams.steps = 99;
        h.sockets[0].open();
        resolveA('late-audio');
        const staleA = await pendingA;

        // The controller captured the injected reader, so resolve the validation read explicitly.
        resolveA = null;
        const beforeValidation = h.sockets.length;
        const invalidPending = controller.start(snapshot({{
          text: 'C', voice: '', supportsVoiceClone: true, requiresPromptText: true,
          promptAudioFile: {{ name: 'c.wav', type: 'audio/wav' }}, promptText: '   ',
        }}));
        await Promise.resolve();
        resolveA('c-audio');
        const invalid = await invalidPending;
        console.log(JSON.stringify({{
          startedB, staleA, invalid,
          socketsAfterValidation: h.sockets.length,
          beforeValidation,
          payload: h.sockets[0].sent[0],
          outputBegins: h.outputBegins,
          players: h.players.length,
          progressKeys: h.progress.map(item => item.key),
          busy: controller.busy,
        }}));
        """
    )
    assert result["startedB"]["started"] is True
    assert result["staleA"]["reason"] == "stale"
    assert result["invalid"]["reason"] == "prompt-text"
    assert result["socketsAfterValidation"] == result["beforeValidation"] == 1
    assert result["payload"] == {
        "text": "B",
        "model": "kokoro",
        "voice": "zf_xiaobei",
        "speed": 1.1,
        "format": "pcm_s16le",
        "binary": False,
        "text_normalization": "wetext",
        "token": "secret",
        "engine_params": {"steps": 4},
    }
    assert result["outputBegins"] == 1
    assert result["players"] == 1
    assert result["progressKeys"][-1] == "studio.stream.prompt_text_required"
    assert result["busy"] is False


def test_saved_profile_omits_residual_prompt_while_temporary_clone_sends_it() -> None:
    result = _node(
        f"""
        import {{ createStreamSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_HARNESS}
        const h = createHarness();
        const controller = createStreamSynthesisController(h.dependencies);

        await controller.start(snapshot({{
          text: 'saved-profile', voice: 'voice_saved',
          supportsProfiles: true, supportsVoiceClone: true, requiresPromptText: true,
          promptAudioFile: {{ name: 'residual.wav', type: 'audio/wav' }},
          promptText: 'residual page prompt',
        }}));
        h.sockets[0].open();
        const savedPayload = h.sockets[0].sent[0];

        await controller.start(snapshot({{
          text: 'temporary-clone', voice: '',
          supportsProfiles: true, supportsVoiceClone: true, requiresPromptText: true,
          promptAudioFile: {{ name: 'temporary.wav', type: 'audio/wav' }},
          promptText: 'temporary reference text',
        }}));
        h.sockets[1].open();
        const temporaryPayload = h.sockets[1].sent[0];

        console.log(JSON.stringify({{
          savedPayload, temporaryPayload, reads: h.reads,
        }}));
        """
    )
    assert result["savedPayload"]["voice"] == "voice_saved"
    assert "prompt_audio" not in result["savedPayload"]
    assert "prompt_text" not in result["savedPayload"]
    assert result["temporaryPayload"]["voice"] == ""
    assert result["temporaryPayload"]["prompt_audio"] == {
        "filename": "temporary.wav",
        "mime_type": "audio/wav",
        "data": "base64:temporary.wav",
    }
    assert result["temporaryPayload"]["prompt_text"] == "temporary reference text"
    assert result["reads"] == ["temporary.wav"]


def test_stop_cancel_refreshes_only_without_a_new_stream_generation() -> None:
    result = _node(
        f"""
        import {{ createStreamSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_HARNESS}

        const noReplacement = createHarness();
        let resolveSingleCancel;
        noReplacement.dependencies.cancelRequest = () => new Promise(resolve => {{ resolveSingleCancel = resolve; }});
        const first = createStreamSynthesisController(noReplacement.dependencies);
        await first.start(snapshot({{ text: 'single' }}));
        noReplacement.sockets[0].open();
        noReplacement.sockets[0].json({{ type: 'started', request_id: 'single-id', segments: 1 }});
        const singleStop = first.stop();
        const refreshBeforeSingleCancel = noReplacement.refreshes;
        resolveSingleCancel({{ ok: true }});
        await singleStop.completion;

        const replacement = createHarness();
        let resolveOldCancel;
        replacement.dependencies.cancelRequest = () => new Promise(resolve => {{ resolveOldCancel = resolve; }});
        const second = createStreamSynthesisController(replacement.dependencies);
        await second.start(snapshot({{ text: 'old' }}));
        replacement.sockets[0].open();
        replacement.sockets[0].json({{ type: 'started', request_id: 'old-id', segments: 1 }});
        const oldStop = second.stop();
        await second.start(snapshot({{ text: 'new' }}));
        resolveOldCancel({{ ok: true }});
        await oldStop.completion;

        console.log(JSON.stringify({{
          refreshBeforeSingleCancel,
          refreshAfterSingleCancel: noReplacement.refreshes,
          refreshAfterReplacement: replacement.refreshes,
          replacementActive: second.active,
        }}));
        """
    )
    assert result == {
        "refreshBeforeSingleCancel": 0,
        "refreshAfterSingleCancel": 1,
        "refreshAfterReplacement": 0,
        "replacementActive": True,
    }


def test_app_refresh_authority_permanently_isolates_cross_controller_late_completions() -> None:
    app = APP.read_text(encoding="utf-8")
    match = re.search(
        r"let latestSynthesisRefreshOwner = '';(?P<body>.*?)\n\}\n\nfunction readList",
        app,
        re.DOTALL,
    )
    assert match
    production_authority = "let latestSynthesisRefreshOwner = '';" + match.group("body") + "\n}"
    result = _node(
        f"""
        const refreshes = [];
        function refreshServiceState() {{ refreshes.push(latestSynthesisRefreshOwner); }}
        {production_authority}

        function pendingCompletion(owner) {{
          let resolve;
          const completion = new Promise(accept => {{ resolve = () => {{
            refreshForSynthesisOwner(owner);
            accept();
          }}; }});
          return {{ completion, resolve }};
        }}

        const outcomes = {{}};

        claimSynthesisRefresh('stream');
        const streamWhileHttpActive = pendingCompletion('stream');
        claimSynthesisRefresh('http');
        streamWhileHttpActive.resolve();
        await streamWhileHttpActive.completion;
        outcomes.streamToActiveHttp = refreshes.splice(0);

        claimSynthesisRefresh('stream');
        const streamAfterHttpDone = pendingCompletion('stream');
        claimSynthesisRefresh('http');
        refreshForSynthesisOwner('http');
        const beforeLateStream = refreshes.length;
        streamAfterHttpDone.resolve();
        await streamAfterHttpDone.completion;
        outcomes.streamToCompletedHttp = {{ refreshes: refreshes.splice(0), beforeLateStream }};

        claimSynthesisRefresh('http');
        const httpWhileStreamActive = pendingCompletion('http');
        claimSynthesisRefresh('stream');
        httpWhileStreamActive.resolve();
        await httpWhileStreamActive.completion;
        outcomes.httpToActiveStream = refreshes.splice(0);

        claimSynthesisRefresh('http');
        const httpAfterStreamDone = pendingCompletion('http');
        claimSynthesisRefresh('stream');
        refreshForSynthesisOwner('stream');
        const beforeLateHttp = refreshes.length;
        httpAfterStreamDone.resolve();
        await httpAfterStreamDone.completion;
        outcomes.httpToCompletedStream = {{ refreshes: refreshes.splice(0), beforeLateHttp }};

        claimSynthesisRefresh('http');
        const httpOnly = pendingCompletion('http');
        httpOnly.resolve();
        await httpOnly.completion;
        claimSynthesisRefresh('stream');
        const streamOnly = pendingCompletion('stream');
        streamOnly.resolve();
        await streamOnly.completion;
        outcomes.noReplacement = refreshes.splice(0);

        console.log(JSON.stringify(outcomes));
        """
    )
    assert result == {
        "streamToActiveHttp": [],
        "streamToCompletedHttp": {"refreshes": ["http"], "beforeLateStream": 1},
        "httpToActiveStream": [],
        "httpToCompletedStream": {"refreshes": ["stream"], "beforeLateHttp": 1},
        "noReplacement": ["http", "stream"],
    }


def test_protocol_message_matrix_terminal_partial_and_error_routing() -> None:
    result = _node(
        f"""
        import {{ createStreamSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_HARNESS}
        const h = createHarness();
        const controller = createStreamSynthesisController(h.dependencies);

        await controller.start(snapshot({{ model: 'moss', prebufferSeconds: 3 }}));
        const first = h.sockets[0];
        first.open();
        first.message(new Uint8Array([1]));
        first.json({{ type: 'started', request_id: 'req-1', segments: 2 }});
        first.json({{ type: 'audio', index: 0, data: 'AA==', sample_rate: 24000, channels: 1 }});
        h.players[0].underrunCount = 2;
        first.json({{ type: 'audio', index: 1, data: 'AQ==', sample_rate: 24000, channels: 1 }});
        first.json({{ type: 'progress', stage: 'waiting_audio' }});
        first.json({{ type: 'progress', stage: 'waiting_audio', elapsed_seconds: 1.25 }});
        first.json({{ type: 'unknown' }});
        first.json({{ type: 'done', total_segments: 2, total_audio_chunks: 2 }});
        const afterDone = {{ active: controller.active, refreshes: h.refreshes, blobs: h.blobs.length }};

        await controller.start(snapshot());
        const malformed = h.sockets[1]; malformed.open(); malformed.message('{{');
        await controller.start(snapshot());
        const server = h.sockets[2]; server.open(); server.json({{ type: 'segment_error', message: 'raw' }});
        await controller.start(snapshot());
        const partial = h.sockets[3]; partial.open(); partial.json({{ type: 'audio', index: 0, data: 'AA==', sample_rate: 24000, channels: 1 }}); partial.serverClose();
        const afterPartial = h.blobs.length;
        await controller.start(snapshot());
        const empty = h.sockets[4]; empty.open(); empty.serverClose();
        await controller.start(snapshot());
        const denied = h.sockets[5]; denied.open(); denied.serverClose(1008);

        console.log(JSON.stringify({{
          afterDone,
          requestIdAfterDone: controller.requestId,
          totalSegments: controller.totalSegments,
          totalAudioChunks: controller.totalAudioChunks,
          progress: h.progress,
          serverErrors: h.serverErrors,
          sessions: h.sessions,
          blobs: h.blobs.length,
          afterPartial,
          refreshes: h.refreshes,
          active: controller.active,
        }}));
        """
    )
    assert result["afterDone"] == {"active": False, "refreshes": 1, "blobs": 1}
    assert result["requestIdAfterDone"] == ""
    keys = [item["key"] for item in result["progress"]]
    for key in (
        "studio.stream.started",
        "studio.stream.audio_received",
        "studio.stream.audio_received_underrun",
        "studio.stream.waiting_audio",
        "studio.stream.waiting_audio_elapsed",
        "studio.stream.completed",
        "studio.stream.invalid_message",
        "studio.stream.closed_partial",
    ):
        assert key in keys
    assert result["serverErrors"] == [{"type": "segment_error", "message": "raw"}]
    assert result["sessions"] == 1
    assert result["afterPartial"] == 2
    assert result["blobs"] == 2
    assert result["refreshes"] == 1
    assert result["active"] is False


def test_stop_open_connecting_stale_callbacks_retirement_and_dispose() -> None:
    result = _node(
        f"""
        import {{ createStreamSynthesisController }} from {json.dumps(MODULE.as_uri())};
        {NODE_HARNESS}
        const h = createHarness();
        const controller = createStreamSynthesisController(h.dependencies);

        await controller.start(snapshot({{ text: 'open' }}));
        const openSocket = h.sockets[0]; openSocket.open();
        openSocket.json({{ type: 'started', request_id: 'req-open', segments: 1 }});
        openSocket.json({{ type: 'audio', index: 0, data: 'AA==', sample_rate: 24000, channels: 1 }});
        const staleMessage = openSocket.onmessage;
        const staleError = openSocket.onerror;
        const staleClose = openSocket.onclose;
        const openStop = controller.stop();
        await openStop.completion;
        const progressAfterStop = h.progress.length;

        await controller.start(snapshot({{ text: 'new' }}));
        const newSocket = h.sockets[1]; newSocket.open();
        staleMessage({{ data: JSON.stringify({{ type: 'done' }}) }});
        staleError({{}});
        staleClose({{ code: 1008 }});

        const newGeneration = controller.generation;
        const connectingStop = controller.stop();
        const connectingSocket = h.sockets[1];
        connectingSocket.open();
        await connectingStop.completion;

        await controller.start(snapshot({{ text: 'retire' }}));
        const retiringSocket = h.sockets[2];
        const retirement = controller.retirePlayer();
        retiringSocket.open();
        await retirement.completion;
        const firstDispose = controller.dispose();
        const secondDispose = controller.dispose();
        await new Promise(resolve => setTimeout(resolve, 0));

        console.log(JSON.stringify({{
          openStop: openStop.stopped,
          openFrames: openSocket.sent,
          openCloseCount: openSocket.closeCount,
          cancels: h.cancels,
          progressAfterStop,
          progressFinal: h.progress.length,
          sessions: h.sessions,
          blobs: h.blobs.length,
          connectingFrames: connectingSocket.sent,
          connectingCloseCount: connectingSocket.closeCount,
          newGeneration,
          retirement: retirement.retired,
          retiringFrames: retiringSocket.sent,
          playerStops: h.players.map(player => player.stopCount),
          playerDisposals: h.players.map(player => player.disposeCount),
          firstDispose, secondDispose,
          active: controller.active, busy: controller.busy,
          hasPlayer: Boolean(controller.player), disposed: controller.disposed,
        }}));
        """
    )
    assert result["openStop"] is True
    assert result["openFrames"][-1] == {"type": "cancel"}
    assert result["cancels"] == ["req-open"]
    assert result["progressFinal"] == result["progressAfterStop"] + 2  # next starts only
    assert result["sessions"] == 0
    assert result["blobs"] == 0
    assert result["connectingFrames"][-1] == {"type": "cancel"}
    assert result["connectingCloseCount"] >= 1
    assert result["retirement"] is True
    assert result["retiringFrames"][-1] == {"type": "cancel"
    }
    assert all(count >= 1 for count in result["playerStops"])
    assert all(count == 1 for count in result["playerDisposals"])
    assert result["firstDispose"] is True
    assert result["secondDispose"] is False
    assert result["active"] is False
    assert result["busy"] is False
    assert result["hasPlayer"] is False
    assert result["disposed"] is True


def test_app_has_single_controller_truth_and_copy_debt_ratchet() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert re.findall(r"\bexport\s+(?:async\s+)?(?:const|function)\s+(\w+)", module) == [
        "createStreamSynthesisController"
    ]
    for forbidden in ("window", "document", "WebSocket", "FileReader", "state.", "i18n"):
        assert forbidden not in module
    for removed in (
        "state.currentWs",
        "state.currentPlayer",
        "state.currentRequestId",
        "state.streamTerminalReceived",
        "state.totalSegments",
        "state.totalAudioChunks",
        "function cleanupWs",
        "function buildPromptAudioPayload",
    ):
        assert removed not in app
    assert "streamSynthesisController.active" in app
    assert "streamSynthesisController.player?.buildWavBlob()" in app
    assert "streamSynthesisController.retirePlayer()" in app
    assert "streamSynthesisController?.dispose()" in app
    assert "if (httpSynthesisController?.active) return;" not in app
    assert "onRefresh: () => refreshForSynthesisOwner('stream')" in app
    assert "modelRequiresPromptText(currentModel()) && !voice && promptAudio" not in app
    assert "payload.prompt_text = els.promptText.value.trim()" not in app

    debt = json.loads(DEBT.read_text(encoding="utf-8"))
    assert len(debt) == 19
    assert Counter(item["target_phase"] for item in debt) == Counter({"1H": 19})
    assert not any(item["target_phase"] == "1E-3C" for item in debt)
