from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "audio-output.js"
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
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}
class FakeAudio {
  constructor(log = []) {
    this.log = log;
    this.listeners = new Map();
    this.attrs = new Map();
    this.paused = true;
    this.ended = false;
    this.currentTime = 7;
    this.playResults = [];
    this.plays = 0;
    this.pauses = 0;
    this.loads = 0;
  }
  set src(value) {
    this.attrs.set('src', value);
    this.paused = true;
    this.ended = false;
    this.log.push(['src', value]);
    this.emit('pause');
  }
  get src() { return this.attrs.get('src') || ''; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  removeEventListener(name, listener) {
    if (this.listeners.get(name) === listener) this.listeners.delete(name);
  }
  removeAttribute(name) {
    this.attrs.delete(name);
    this.log.push(['remove', name]);
  }
  emit(name) { this.listeners.get(name)?.({ type: name, target: this }); }
  play() {
    this.plays += 1;
    this.paused = false;
    this.ended = false;
    this.emit('play');
    return this.playResults.shift() ?? Promise.resolve();
  }
  pause() {
    this.pauses += 1;
    this.paused = true;
    this.emit('pause');
  }
  load() { this.loads += 1; }
}
function harness({ triggerThrows = false } = {}) {
  const log = [];
  const audio = new FakeAudio(log);
  const created = [];
  const revoked = [];
  const downloads = [];
  const states = [];
  const autoplayErrors = [];
  const timers = new Map();
  const cancelledTimers = [];
  let urlSerial = 0;
  let timerSerial = 0;
  const dependencies = {
    element: audio,
    createObjectURL: blob => {
      const url = `blob:${++urlSerial}:${blob.name}`;
      created.push(url);
      log.push(['create', url]);
      return url;
    },
    revokeObjectURL: url => { revoked.push(url); log.push(['revoke', url]); },
    triggerDownload: payload => {
      downloads.push(payload);
      log.push(['download', payload.url, payload.filename]);
      if (triggerThrows) throw new Error('download blocked');
    },
    schedule: (callback, delay) => {
      const id = ++timerSerial;
      timers.set(id, { callback, delay });
      return id;
    },
    cancelSchedule: id => { cancelledTimers.push(id); timers.delete(id); },
    callbacks: {
      onStateChange: state => states.push({
        blob: state.blob?.name ?? null,
        downloadable: state.downloadableBlob?.name ?? null,
        playing: state.playing,
        hasSource: state.hasSource,
      }),
      onAutoplayRejected: error => autoplayErrors.push(error.message),
    },
  };
  const runTimers = () => {
    for (const [id, timer] of [...timers.entries()]) {
      timers.delete(id);
      timer.callback();
    }
  };
  return { audio, created, revoked, downloads, states, autoplayErrors, timers, cancelledTimers, dependencies, runTimers, log };
}
"""


def test_source_begin_replace_stop_and_event_ownership() -> None:
    result = _node(
        f"""
        import {{ createAudioOutputController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const controller = createAudioOutputController(h.dependencies);
        const a = {{ name: 'A' }};
        const b = {{ name: 'B' }};
        const first = controller.setBlob(a, {{ autoplay: false }});
        const afterFirst = {{
          src: h.audio.src, blob: controller.blob.name,
          downloadable: controller.downloadableBlob.name,
          playing: controller.playing, hasSource: controller.hasSource,
        }};
        const begun = controller.beginResult();
        const afterBegin = {{
          src: h.audio.src, blob: controller.blob.name,
          downloadable: controller.downloadableBlob,
          revoked: [...h.revoked], hasSource: controller.hasSource,
        }};
        const second = controller.setBlob(b, {{ autoplay: false }});
        h.audio.paused = false;
        h.audio.emit('play');
        const afterPlay = controller.playing;
        h.audio.paused = true;
        h.audio.emit('pause');
        const afterPause = controller.playing;
        h.audio.paused = false;
        h.audio.ended = true;
        h.audio.emit('ended');
        const afterEnded = controller.playing;
        h.audio.currentTime = 14;
        const stopped = controller.stopPlayback();
        console.log(JSON.stringify({{
          first, begun, second, afterFirst, afterBegin,
          afterSecond: {{ src: h.audio.src, blob: controller.blob.name, downloadable: controller.downloadableBlob.name }},
          afterPlay, afterPause, afterEnded,
          stopped: {{ status: stopped.status, blob: stopped.blob.name, url: stopped.url }},
          stopState: {{ currentTime: h.audio.currentTime, playing: controller.playing, src: h.audio.src, downloadable: controller.downloadableBlob.name }},
          created: h.created, revoked: h.revoked, log: h.log,
        }}));
        """
    )
    assert result["afterFirst"] == {
        "src": "blob:1:A",
        "blob": "A",
        "downloadable": "A",
        "playing": False,
        "hasSource": True,
    }
    assert result["afterBegin"] == {
        "src": "blob:1:A",
        "blob": "A",
        "downloadable": None,
        "revoked": [],
        "hasSource": True,
    }
    assert result["afterSecond"] == {"src": "blob:2:B", "blob": "B", "downloadable": "B"}
    assert result["created"] == ["blob:1:A", "blob:2:B"]
    assert result["revoked"] == ["blob:1:A"]
    assert result["log"].index(["src", "blob:2:B"]) < result["log"].index(["revoke", "blob:1:A"])
    assert [result["afterPlay"], result["afterPause"], result["afterEnded"]] == [True, False, False]
    assert result["stopState"] == {
        "currentTime": 0,
        "playing": False,
        "src": "blob:2:B",
        "downloadable": "B",
    }
    assert result["stopped"] == {"status": "stopped", "blob": "B", "url": "blob:2:B"}


def test_autoplay_generation_rejects_only_the_current_source() -> None:
    result = _node(
        f"""
        import {{ createAudioOutputController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const controller = createAudioOutputController(h.dependencies);
        const aPlay = deferred();
        const bPlay = deferred();
        h.audio.playResults.push(aPlay.promise, bPlay.promise);
        const a = controller.setBlob({{ name: 'A' }}, {{ autoplay: true }});
        const b = controller.setBlob({{ name: 'B' }}, {{ autoplay: true }});
        bPlay.resolve();
        const bOutcome = await b.autoplayCompletion;
        aPlay.reject(new Error('late A rejection'));
        const aOutcome = await a.autoplayCompletion;
        const afterStale = {{ playing: controller.playing, blob: controller.blob.name, errors: [...h.autoplayErrors] }};
        const cPlay = deferred();
        h.audio.playResults.push(cPlay.promise);
        const c = controller.setBlob({{ name: 'C' }}, {{ autoplay: true }});
        cPlay.reject(new Error('current C rejection'));
        const cOutcome = await c.autoplayCompletion;
        console.log(JSON.stringify({{
          aOutcome, bOutcome, cOutcome, afterStale,
          final: {{ playing: controller.playing, blob: controller.blob.name, downloadable: controller.downloadableBlob.name, src: h.audio.src }},
          errors: h.autoplayErrors, revoked: h.revoked,
        }}));
        """
    )
    assert result["aOutcome"] == "stale"
    assert result["bOutcome"] == "played"
    assert result["afterStale"] == {"playing": True, "blob": "B", "errors": []}
    assert result["cOutcome"] == "rejected"
    assert result["final"] == {
        "playing": False,
        "blob": "C",
        "downloadable": "C",
        "src": "blob:3:C",
    }
    assert result["errors"] == ["current C rejection"]
    assert result["revoked"] == ["blob:1:A", "blob:2:B"]


def test_download_uses_temporary_url_and_cleans_success_and_trigger_failure() -> None:
    result = _node(
        f"""
        import {{ createAudioOutputController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const success = harness();
        const first = createAudioOutputController(success.dependencies);
        first.setBlob({{ name: 'persistent' }});
        const download = first.download({{ filename: 'angevoice_now.wav' }});
        const sourceBeforeCleanup = success.audio.src;
        const timerDelays = [...success.timers.values()].map(timer => timer.delay);
        success.runTimers();

        const failure = harness({{ triggerThrows: true }});
        const second = createAudioOutputController(failure.dependencies);
        second.setBlob({{ name: 'player' }});
        const failed = second.download({{ blob: {{ name: 'stream' }}, filename: 'angevoice_stream.wav' }});
        failure.runTimers();
        console.log(JSON.stringify({{
          success: {{
            status: download.status, sourceBeforeCleanup, sourceAfterCleanup: success.audio.src,
            created: success.created, revoked: success.revoked, downloads: success.downloads,
            timerDelays, downloadable: first.downloadableBlob.name,
          }},
          failure: {{
            status: failed.status, error: failed.error.message,
            created: failure.created, revoked: failure.revoked,
            downloads: failure.downloads, source: failure.audio.src,
          }},
        }}));
        """
    )
    assert result["success"] == {
        "status": "scheduled",
        "sourceBeforeCleanup": "blob:1:persistent",
        "sourceAfterCleanup": "blob:1:persistent",
        "created": ["blob:1:persistent", "blob:2:persistent"],
        "revoked": ["blob:2:persistent"],
        "downloads": [{"url": "blob:2:persistent", "filename": "angevoice_now.wav"}],
        "timerDelays": [500],
        "downloadable": "persistent",
    }
    assert result["failure"] == {
        "status": "trigger_failed",
        "error": "download blocked",
        "created": ["blob:1:player", "blob:2:stream"],
        "revoked": ["blob:2:stream"],
        "downloads": [{"url": "blob:2:stream", "filename": "angevoice_stream.wav"}],
        "source": "blob:1:player",
    }


def test_dispose_cleans_every_owned_resource_once_and_silences_continuations() -> None:
    result = _node(
        f"""
        import {{ createAudioOutputController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const controller = createAudioOutputController(h.dependencies);
        const pendingPlay = deferred();
        h.audio.playResults.push(pendingPlay.promise);
        const set = controller.setBlob({{ name: 'result' }}, {{ autoplay: true }});
        controller.download({{ filename: 'one.wav' }});
        controller.download({{ blob: {{ name: 'stream' }}, filename: 'two.wav' }});
        const callbacksBefore = h.states.length;
        controller.dispose();
        controller.dispose();
        h.audio.paused = false;
        h.audio.emit('play');
        pendingPlay.reject(new Error('late rejection'));
        const autoplayOutcome = await set.autoplayCompletion;
        const afterSet = controller.setBlob({{ name: 'late' }});
        const afterDownload = controller.download({{ blob: {{ name: 'late' }}, filename: 'late.wav' }});
        console.log(JSON.stringify({{
          autoplayOutcome, callbacksBefore, callbacksAfter: h.states.length,
          created: h.created, revoked: h.revoked,
          duplicateRevocations: h.revoked.length - new Set(h.revoked).size,
          cancelledTimers: h.cancelledTimers,
          listeners: h.audio.listeners.size, src: h.audio.src,
          pauses: h.audio.pauses, loads: h.audio.loads, currentTime: h.audio.currentTime,
          disposed: controller.disposed, hasSource: controller.hasSource,
          blob: controller.blob, downloadable: controller.downloadableBlob,
          afterSet: afterSet.status, afterDownload: afterDownload.status,
        }}));
        """
    )
    assert result["autoplayOutcome"] == "stale"
    assert result["callbacksAfter"] == result["callbacksBefore"]
    assert result["created"] == ["blob:1:result", "blob:2:result", "blob:3:stream"]
    assert result["revoked"] == ["blob:1:result", "blob:2:result", "blob:3:stream"]
    assert result["duplicateRevocations"] == 0
    assert result["cancelledTimers"] == [1, 2]
    assert result["listeners"] == 0
    assert result["src"] == ""
    assert result["currentTime"] == 0
    assert result["disposed"] is True
    assert result["hasSource"] is False
    assert result["blob"] is None and result["downloadable"] is None
    assert result["afterSet"] == "disposed" and result["afterDownload"] == "disposed"


def test_repeated_replace_download_timer_and_dispose_races_have_no_tombstones() -> None:
    result = _node(
        f"""
        import {{ createAudioOutputController }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const controller = createAudioOutputController(h.dependencies);
        controller.setBlob({{ name: 'A' }});
        for (const name of ['B', 'C', 'D']) {{
          controller.setBlob({{ name }});
          controller.download({{ filename: `${{name}}.wav` }});
          h.runTimers();
        }}
        controller.setBlob({{ name: 'E' }});
        controller.download({{ filename: 'pending.wav' }});
        const lateCallbacks = [...h.timers.values()].map(timer => timer.callback);
        controller.dispose();
        lateCallbacks.forEach(callback => callback());
        controller.dispose();
        console.log(JSON.stringify({{
          created: h.created,
          revoked: h.revoked,
          duplicateRevocations: h.revoked.length - new Set(h.revoked).size,
          unrevoked: h.created.filter(url => !h.revoked.includes(url)),
          timers: h.timers.size,
          disposed: controller.disposed,
        }}));
        """
    )
    assert len(result["created"]) == 9
    assert len(result["revoked"]) == 9
    assert set(result["created"]) == set(result["revoked"])
    assert result["duplicateRevocations"] == 0
    assert result["unrevoked"] == []
    assert result["timers"] == 0
    assert result["disposed"] is True


def test_module_is_pure_esm_and_app_is_only_the_composition_root() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "window" not in module
    assert "document" not in module
    assert "globalThis.URL" not in module
    assert "setTimeout" not in module
    assert "./common/i18n.js" not in module
    assert "revokedUrls" not in module
    assert module.count("new Set()") == 1
    assert "if (!url || !liveUrls.has(url)) return false;" in module
    assert module.index("revokeUrl(url);") < module.index("liveUrls.delete(url);")
    assert re.findall(r"\bexport\s+(?:async\s+)?(?:const|function)\s+(\w+)", module) == [
        "createAudioOutputController"
    ]
    assert "function initializeAudioOutput()" in app
    assert app.index("initializeAudioOutput();") < app.index("initializeReferenceAudioPreview();")
    assert "URL.createObjectURL" not in app
    assert "URL.revokeObjectURL" not in app
    assert "state.lastBlob" not in app
    assert "state.playing" not in app
    assert not re.search(r"els\.audio\.src\s*=", app)
    assert not re.search(r"els\.audio\.(?:play|pause)\s*\(", app)
    assert "audioOutputController.beginResult();" in app
    assert app.count("audioOutputController.setBlob(") == 2
    assert "audioOutputController.stopPlayback();" in app
    assert "audioOutputController.downloadableBlob || streamSynthesisController.player?.buildWavBlob()" in app
    assert "audioOutputController?.dispose();" in app
    assert "state.streamPlaying" not in app
    assert "Boolean(streamSynthesisController?.player?.playing)" in app
    assert "onOutputBegin: () => audioOutputController.beginResult()" in app
    assert "onBlob: (blob, options) => audioOutputController.setBlob(blob, options)" in app
    assert "audioOutputController.beginResult()" not in re.search(
        r"function synthesizeStream\(.*?\n}", app, re.DOTALL
    ).group(0)


def test_copy_debt_reflects_the_p1_2b_ratchet() -> None:
    registered = json.loads(DEBT.read_text(encoding="utf-8"))
    assert registered == []
