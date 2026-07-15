from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "stream-player.js"
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
class FakeAudioBuffer {
  constructor(channels, frameCount, sampleRate) {
    this.numberOfChannels = channels;
    this.length = frameCount;
    this.sampleRate = sampleRate;
    this.duration = frameCount / sampleRate;
    this.channelData = Array.from({ length: channels }, () => new Float32Array(frameCount));
  }
  getChannelData(channel) { return this.channelData[channel]; }
}

class FakeBufferSource {
  constructor(context, serial) {
    this.context = context;
    this.serial = serial;
    this.buffer = null;
    this.destination = null;
    this.startTimes = [];
    this.stopCount = 0;
    this.ended = false;
    this.onended = null;
  }
  connect(destination) {
    this.destination = destination;
    this.context.log.push(['source-connect', this.serial]);
  }
  start(time) {
    this.startTimes.push(time);
    this.context.log.push(['source-start', this.serial, time]);
  }
  stop() {
    this.stopCount += 1;
    this.context.log.push(['source-stop', this.serial]);
    if (this.ended) throw new Error('already ended');
  }
  end() {
    this.ended = true;
    this.context.log.push(['source-end', this.serial]);
    this.onended?.();
  }
}

class FakeAudioContext {
  constructor(harness, options) {
    this.harness = harness;
    this.options = options;
    this.sampleRate = harness.actualSampleRate || options.sampleRate;
    this.currentTime = harness.currentTime;
    this.state = harness.contextState;
    this.destination = { name: 'destination' };
    this.sources = [];
    this.buffers = [];
    this.resumeCount = 0;
    this.closeCount = 0;
    this.log = harness.log;
    this.log.push(['context-create', this.sampleRate]);
  }
  createBuffer(channels, frameCount, sampleRate) {
    const buffer = new FakeAudioBuffer(channels, frameCount, sampleRate);
    this.buffers.push(buffer);
    this.log.push(['buffer-create', channels, frameCount, sampleRate]);
    return buffer;
  }
  createBufferSource() {
    const source = new FakeBufferSource(this, ++this.harness.sourceSerial);
    this.sources.push(source);
    this.log.push(['source-create', source.serial]);
    return source;
  }
  resume() {
    this.resumeCount += 1;
    this.state = 'running';
    this.log.push(['context-resume']);
    return Promise.resolve();
  }
  close() {
    this.closeCount += 1;
    this.log.push(['context-close']);
    return this.harness.closeReject
      ? Promise.reject(new Error('close rejected'))
      : Promise.resolve();
  }
}

function harness({ actualSampleRate = null, currentTime = 10, contextState = 'running', closeReject = false } = {}) {
  const h = {
    actualSampleRate, currentTime, contextState, closeReject,
    contexts: [], log: [], sourceSerial: 0, playingChanges: [],
  };
  h.dependencies = {
    createAudioContext: options => {
      const context = new FakeAudioContext(h, options);
      h.contexts.push(context);
      return context;
    },
    decodeBase64: value => Uint8Array.from(Buffer.from(value, 'base64')),
    createBlob: (parts, options) => new Blob(parts, options),
    callbacks: { onPlayingChange: value => h.playingChanges.push(value) },
  };
  return h;
}

function pcmBase64(samples) {
  const bytes = Buffer.alloc(samples.length * 2);
  samples.forEach((sample, index) => bytes.writeInt16LE(sample, index * 2));
  return bytes.toString('base64');
}

async function blobBytes(blob) {
  return [...new Uint8Array(await blob.arrayBuffer())];
}
"""


def test_import_is_pure_and_construction_is_lazy_with_defaults() -> None:
    result = _node(
        f"""
        for (const name of ['window', 'document', 'AudioContext', 'atob']) {{
          Object.defineProperty(globalThis, name, {{
            configurable: true,
            get() {{ throw new Error(`import touched ${{name}}`); }},
          }});
        }}
        const {{ createStreamPlayer }} = await import({json.dumps(MODULE.as_uri())});
        {NODE_FIXTURE}
        const h = harness();
        const player = createStreamPlayer(h.dependencies);
        console.log(JSON.stringify({{
          contexts: h.contexts.length,
          defaults: {{
            sampleRate: player.sampleRate,
            channels: player.channels,
            prebufferSeconds: player.prebufferSeconds,
          }},
          playing: player.playing,
          hasAudio: player.hasAudio,
          pcmChunkCount: player.pcmChunkCount,
          audioChunkCount: player.audioChunkCount,
          underrunCount: player.underrunCount,
          disposed: player.disposed,
          frozen: Object.isFrozen(player),
        }}));
        """
    )
    assert result == {
        "contexts": 0,
        "defaults": {"sampleRate": 24000, "channels": 1, "prebufferSeconds": 0.25},
        "playing": False,
        "hasAudio": False,
        "pcmChunkCount": 0,
        "audioChunkCount": 0,
        "underrunCount": 0,
        "disposed": False,
        "frozen": True,
    }


def test_prebuffer_clamps_and_only_moves_an_unscheduled_context() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness({{ currentTime: 4 }});
        const player = createStreamPlayer(h.dependencies);
        const values = [];
        values.push(player.setPrebuffer(-3));
        values.push(player.setPrebuffer(0));
        values.push(player.setPrebuffer('2.5'));
        values.push(player.setPrebuffer(99));
        values.push(player.setPrebuffer(Number.NaN));
        player.setPrebuffer(0);
        player.init(24000, 1);
        const beforeContextUpdate = player.bufferedSeconds();
        player.setPrebuffer(3);
        const afterContextUpdate = player.bufferedSeconds();
        player.enqueuePCM(pcmBase64([1, 2]), 24000, 1);
        const beforeScheduledUpdate = player.bufferedSeconds();
        player.setPrebuffer(9);
        const afterScheduledUpdate = player.bufferedSeconds();
        console.log(JSON.stringify({{
          values, contexts: h.contexts.length,
          beforeContextUpdate, afterContextUpdate,
          beforeScheduledUpdate, afterScheduledUpdate,
          finalPrebuffer: player.prebufferSeconds,
        }}));
        """
    )
    assert result["values"] == [0, 0, 2.5, 12, 12]
    assert result["contexts"] == 1
    assert result["beforeContextUpdate"] == 0
    assert result["afterContextUpdate"] == 3
    assert result["beforeScheduledUpdate"] == result["afterScheduledUpdate"]
    assert result["finalPrebuffer"] == 9


def test_first_and_continuous_pcm_chunks_preserve_decode_channel_and_schedule_contracts() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness({{ actualSampleRate: 48000, currentTime: 10, contextState: 'suspended' }});
        const player = createStreamPlayer({{
          ...h.dependencies,
          defaults: {{ sampleRate: 24000, channels: 1, prebufferSeconds: 0.5 }},
        }});
        player.enqueuePCM(pcmBase64([32767, -32768, 16384, -16384]), 16000, 2);
        const context = h.contexts[0];
        const first = context.sources[0];
        const firstBuffer = context.buffers[0];
        player.enqueuePCM(pcmBase64([1000, -1000, 2000, -2000]), 16000, 2);
        const second = context.sources[1];
        console.log(JSON.stringify({{
          contextCount: h.contexts.length,
          requestedSampleRate: context.options.sampleRate,
          actualSampleRate: player.sampleRate,
          channels: player.channels,
          resumeCount: context.resumeCount,
          firstStart: first.startTimes[0],
          secondStart: second.startTimes[0],
          firstDuration: firstBuffer.duration,
          channel0: [...firstBuffer.channelData[0]],
          channel1: [...firstBuffer.channelData[1]],
          buffered: player.bufferedSeconds(),
          playing: player.playing,
          playingChanges: h.playingChanges,
          audioChunkCount: player.audioChunkCount,
          pcmChunkCount: player.pcmChunkCount,
          underrunCount: player.underrunCount,
        }}));
        """
    )
    assert result["contextCount"] == 1
    assert result["requestedSampleRate"] == 16000
    assert result["actualSampleRate"] == 48000
    assert result["channels"] == 2
    assert result["resumeCount"] == 1
    assert result["firstStart"] == 10.5
    assert abs(result["secondStart"] - (10.5 + result["firstDuration"])) < 1e-12
    assert abs(result["channel0"][0] - 1.0) < 1e-7
    assert abs(result["channel0"][1] - (16384 / 32767)) < 1e-6
    assert abs(result["channel1"][0] - (-32768 / 32767)) < 1e-6
    assert abs(result["channel1"][1] - (-16384 / 32767)) < 1e-6
    assert result["buffered"] > 0.5
    assert result["playing"] is True
    assert result["playingChanges"] == [True]
    assert result["audioChunkCount"] == 2
    assert result["pcmChunkCount"] == 2
    assert result["underrunCount"] == 0


def test_underrun_source_end_and_generation_isolate_stale_callbacks() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness({{ currentTime: 0 }});
        const player = createStreamPlayer({{
          ...h.dependencies,
          defaults: {{ sampleRate: 24000, channels: 1, prebufferSeconds: 0 }},
        }});
        player.enqueuePCM(pcmBase64([1, 2]), 24000, 1);
        player.enqueuePCM(pcmBase64([3, 4]), 24000, 1);
        const context = h.contexts[0];
        const first = context.sources[0];
        const second = context.sources[1];
        first.end();
        const afterFirstEnd = {{ playing: player.playing, active: player.activeSourceCount }};
        second.end();
        const afterLastEnd = {{ playing: player.playing, active: player.activeSourceCount }};

        player.enqueuePCM(pcmBase64([5, 6]), 24000, 1);
        const stale = context.sources[2];
        const underrunsBeforeGap = player.underrunCount;
        context.currentTime = 1;
        player.enqueuePCM(pcmBase64([7, 8]), 24000, 1);
        const underrunDelta = player.underrunCount - underrunsBeforeGap;
        player.stop();
        const callbackCountAfterStop = h.playingChanges.length;
        player.enqueuePCM(pcmBase64([9, 10]), 24000, 1);
        const current = context.sources[4];
        const beforeStaleEnd = {{
          playing: player.playing,
          active: player.activeSourceCount,
          callbackCount: h.playingChanges.length,
          generation: player.generation,
        }};
        stale.end();
        const afterStaleEnd = {{
          playing: player.playing,
          active: player.activeSourceCount,
          callbackCount: h.playingChanges.length,
          generation: player.generation,
        }};
        current.end();
        console.log(JSON.stringify({{
          afterFirstEnd, afterLastEnd, underrunDelta,
          callbackCountAfterStop, beforeStaleEnd, afterStaleEnd,
          final: {{ playing: player.playing, active: player.activeSourceCount }},
          playingChanges: h.playingChanges,
        }}));
        """
    )
    assert result["afterFirstEnd"] == {"playing": True, "active": 1}
    assert result["afterLastEnd"] == {"playing": False, "active": 0}
    assert result["underrunDelta"] == 1
    assert result["beforeStaleEnd"] == result["afterStaleEnd"]
    assert result["final"] == {"playing": False, "active": 0}
    assert result["playingChanges"] == [True, False, True, False, True, False]


def test_stop_is_idempotent_and_preserves_pcm_for_wav_download() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const player = createStreamPlayer(h.dependencies);
        player.enqueuePCM(pcmBase64([1, -1]), 24000, 1);
        player.enqueuePCM(pcmBase64([2, -2]), 24000, 1);
        const sources = [...h.contexts[0].sources];
        player.stop();
        const callbacksAfterStop = h.playingChanges.length;
        player.stop();
        sources.forEach(source => source.end());
        const blob = player.buildWavBlob();
        console.log(JSON.stringify({{
          playing: player.playing,
          hasAudio: player.hasAudio,
          pcmChunkCount: player.pcmChunkCount,
          audioChunkCount: player.audioChunkCount,
          activeSourceCount: player.activeSourceCount,
          stopCounts: sources.map(source => source.stopCount),
          callbacksAfterStop,
          callbacksFinal: h.playingChanges.length,
          contextCloseCount: h.contexts[0].closeCount,
          wavBytes: await blobBytes(blob),
        }}));
        """
    )
    assert result["playing"] is False
    assert result["hasAudio"] is True
    assert result["pcmChunkCount"] == 2
    assert result["audioChunkCount"] == 0
    assert result["activeSourceCount"] == 0
    assert result["stopCounts"] == [1, 1]
    assert result["callbacksAfterStop"] == result["callbacksFinal"]
    assert result["contextCloseCount"] == 0
    assert result["wavBytes"][:4] == list(b"RIFF")


def test_wav_bytes_cover_mono_stereo_multiple_chunks_stop_and_dispose() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const monoHarness = harness({{ actualSampleRate: 24000 }});
        const mono = createStreamPlayer(monoHarness.dependencies);
        const empty = mono.buildWavBlob();
        mono.enqueuePCM(pcmBase64([1, -2]), 24000, 1);
        mono.enqueuePCM(pcmBase64([32767, -32768]), 24000, 1);
        mono.stop();
        const monoBlob = mono.buildWavBlob();
        const monoBytes = await blobBytes(monoBlob);

        const stereoHarness = harness({{ actualSampleRate: 48000 }});
        const stereo = createStreamPlayer(stereoHarness.dependencies);
        stereo.enqueuePCM(pcmBase64([100, -100, 200, -200]), 48000, 2);
        const stereoBlob = stereo.buildWavBlob();
        const stereoBytes = await blobBytes(stereoBlob);
        stereo.dispose();

        const text = (bytes, start, length) => String.fromCharCode(...bytes.slice(start, start + length));
        const u16 = (bytes, offset) => new DataView(Uint8Array.from(bytes).buffer).getUint16(offset, true);
        const u32 = (bytes, offset) => new DataView(Uint8Array.from(bytes).buffer).getUint32(offset, true);
        console.log(JSON.stringify({{
          empty: empty === null,
          mono: {{
            type: monoBlob.type, length: monoBytes.length,
            riff: text(monoBytes, 0, 4), wave: text(monoBytes, 8, 4), fmt: text(monoBytes, 12, 4), data: text(monoBytes, 36, 4),
            riffLength: u32(monoBytes, 4), fmtLength: u32(monoBytes, 16), format: u16(monoBytes, 20),
            channels: u16(monoBytes, 22), sampleRate: u32(monoBytes, 24), byteRate: u32(monoBytes, 28),
            blockAlign: u16(monoBytes, 32), bits: u16(monoBytes, 34), dataLength: u32(monoBytes, 40),
            pcm: monoBytes.slice(44),
          }},
          stereo: {{
            type: stereoBlob.type, length: stereoBytes.length,
            channels: u16(stereoBytes, 22), sampleRate: u32(stereoBytes, 24), byteRate: u32(stereoBytes, 28),
            blockAlign: u16(stereoBytes, 32), bits: u16(stereoBytes, 34), dataLength: u32(stereoBytes, 40),
            pcm: stereoBytes.slice(44),
          }},
          afterDispose: stereo.buildWavBlob() === null,
        }}));
        """
    )
    assert result["empty"] is True
    assert result["mono"] == {
        "type": "audio/wav",
        "length": 52,
        "riff": "RIFF",
        "wave": "WAVE",
        "fmt": "fmt ",
        "data": "data",
        "riffLength": 44,
        "fmtLength": 16,
        "format": 1,
        "channels": 1,
        "sampleRate": 24000,
        "byteRate": 48000,
        "blockAlign": 2,
        "bits": 16,
        "dataLength": 8,
        "pcm": [1, 0, 254, 255, 255, 127, 0, 128],
    }
    assert result["stereo"] == {
        "type": "audio/wav",
        "length": 52,
        "channels": 2,
        "sampleRate": 48000,
        "byteRate": 192000,
        "blockAlign": 4,
        "bits": 16,
        "dataLength": 8,
        "pcm": [100, 0, 156, 255, 200, 0, 56, 255],
    }
    assert result["afterDispose"] is True


def test_dispose_replacement_and_close_rejection_have_no_stale_side_effects() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const unhandled = [];
        process.on('unhandledRejection', error => unhandled.push(error.message));
        const aHarness = harness({{ closeReject: true }});
        const bHarness = harness();
        const a = createStreamPlayer(aHarness.dependencies);
        const b = createStreamPlayer(bHarness.dependencies);
        a.enqueuePCM(pcmBase64([1, 2]), 24000, 1);
        const staleSource = aHarness.contexts[0].sources[0];
        b.enqueuePCM(pcmBase64([3, 4]), 24000, 1);
        const bBefore = {{
          playing: b.playing, active: b.activeSourceCount,
          callbacks: [...bHarness.playingChanges],
        }};
        const firstDispose = a.dispose();
        const secondDispose = a.dispose();
        staleSource.end();
        const enqueueAfterDispose = a.enqueuePCM(pcmBase64([5, 6]), 24000, 1);
        await Promise.resolve();
        await new Promise(resolve => setTimeout(resolve, 0));
        const bAfter = {{
          playing: b.playing, active: b.activeSourceCount,
          callbacks: [...bHarness.playingChanges],
        }};
        b.dispose();
        console.log(JSON.stringify({{
          firstDispose, secondDispose, enqueueAfterDispose,
          a: {{
            disposed: a.disposed, playing: a.playing, hasAudio: a.hasAudio,
            pcmChunkCount: a.pcmChunkCount, active: a.activeSourceCount,
            hasContext: a.hasContext, closeCount: aHarness.contexts[0].closeCount,
            stopCount: staleSource.stopCount, callbacks: aHarness.playingChanges,
          }},
          bBefore, bAfter, bCloseCount: bHarness.contexts[0].closeCount,
          unhandled,
        }}));
        """
    )
    assert result["firstDispose"] is True
    assert result["secondDispose"] is False
    assert result["enqueueAfterDispose"] is None
    assert result["a"] == {
        "disposed": True,
        "playing": False,
        "hasAudio": False,
        "pcmChunkCount": 0,
        "active": 0,
        "hasContext": False,
        "closeCount": 1,
        "stopCount": 1,
        "callbacks": [True],
    }
    assert result["bBefore"] == result["bAfter"] == {
        "playing": True,
        "active": 1,
        "callbacks": [True],
    }
    assert result["bCloseCount"] == 1
    assert result["unhandled"] == []


def test_reinitialization_retires_context_and_invalidates_old_generation() -> None:
    result = _node(
        f"""
        import {{ createStreamPlayer }} from {json.dumps(MODULE.as_uri())};
        {NODE_FIXTURE}
        const h = harness();
        const player = createStreamPlayer(h.dependencies);
        player.enqueuePCM(pcmBase64([1, 2]), 24000, 1);
        const oldContext = h.contexts[0];
        const oldSource = oldContext.sources[0];
        const oldGeneration = player.generation;
        player.init(16000, 2);
        const callbacksBeforeStale = h.playingChanges.length;
        oldSource.end();
        console.log(JSON.stringify({{
          contextCount: h.contexts.length,
          oldCloseCount: oldContext.closeCount,
          oldStopCount: oldSource.stopCount,
          oldGeneration,
          newGeneration: player.generation,
          callbacksBeforeStale,
          callbacksAfterStale: h.playingChanges.length,
          playing: player.playing,
          active: player.activeSourceCount,
          hasAudio: player.hasAudio,
          requestedSampleRate: h.contexts[1].options.sampleRate,
          channels: player.channels,
        }}));
        """
    )
    assert result["contextCount"] == 2
    assert result["oldCloseCount"] == 1
    assert result["oldStopCount"] == 1
    assert result["newGeneration"] > result["oldGeneration"]
    assert result["callbacksBeforeStale"] == result["callbacksAfterStale"]
    assert result["playing"] is False
    assert result["active"] == 0
    assert result["hasAudio"] is False
    assert result["requestedSampleRate"] == 16000
    assert result["channels"] == 2


def test_app_composes_player_through_the_stream_lifecycle_controller() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "window" not in module
    assert "document" not in module
    assert "state." not in module
    assert "atob" not in module
    assert "i18n" not in module
    assert re.findall(r"\bexport\s+(?:async\s+)?(?:const|function)\s+(\w+)", module) == [
        "createStreamPlayer"
    ]
    assert "import { createStreamPlayer } from './studio/stream-player.js';" in app
    assert "import { createStreamSynthesisController } from './studio/stream-synthesis.js';" in app
    assert "class StreamPlayer" not in app
    assert "function decodeBase64" not in app
    assert "state.streamPlaying" not in app
    assert "streamPlaying:" not in app
    assert "Boolean(streamSynthesisController?.player?.playing)" in app
    assert "streamSynthesisController?.player?.hasAudio" in app
    assert "state.currentPlayer" not in app
    assert "state.currentWs" not in app
    assert "if (!event.persisted) streamSynthesisController?.dispose();" in app
    assert "callbacks.onStateChange?.()" in app

    http_start = re.search(
        r"onStart: \(\) => \{(?P<body>.*?)\n\s*},\n\s*onProgress:",
        app,
        re.DOTALL,
    )
    assert http_start
    assert http_start.group("body").index("streamSynthesisController.retirePlayer();") < http_start.group(
        "body"
    ).index("audioOutputController.beginResult();")

    registered = json.loads(DEBT.read_text(encoding="utf-8"))
    assert len(registered) == 19
    assert Counter(item["target_phase"] for item in registered) == Counter({"1H": 19})
