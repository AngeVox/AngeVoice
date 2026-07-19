const code = (copyId, template) => ({ type: 'codeBlock', copyId, template });
const text = key => ({ type: 'text', key });
const literal = value => ({ type: 'text', value });
const codeLiteral = value => ({ type: 'code', value });
const strong = key => ({ type: 'strong', key });
const link = (key, href) => ({ type: 'link', key, href });

const INLINE_FRAGMENTS = Object.freeze({
  'docs.hero.desc': [codeLiteral('8000'), codeLiteral('8100'), codeLiteral('8101'), codeLiteral('8102')],
  'docs.quick.body': [codeLiteral('BASE_URL=http://localhost:8000')],
  'docs.quick.auth': [codeLiteral('KOKORO_API_KEY'), codeLiteral('Authorization: Bearer YOUR_TOKEN'), codeLiteral('token')],
  'docs.models.legacy': [codeLiteral('moss-nano-cpu'), codeLiteral('moss-nano-cuda'), codeLiteral('moss')],
  'docs.models.kokoro.id': [codeLiteral('kokoro')],
  'docs.models.kokoro.clone': [codeLiteral('.pt')],
  'docs.models.moss.id': [codeLiteral('moss')],
  'docs.models.zip.id': [codeLiteral('zipvoice')],
  'docs.openai.body': [codeLiteral('/v1/audio/speech'), strong('docs.openai.emphasis'), codeLiteral('/api/tts')],
  'docs.openai.ffmpeg': [codeLiteral('telegram_voice'), codeLiteral('ogg_opus'), codeLiteral('m4a'), codeLiteral('mp3')],
  'docs.moss_clone.body': [codeLiteral('models/models--hexgrad--Kokoro-82M-v1.1-zh/voices'), codeLiteral('.pt')],
  'docs.moss_clone.http.location': [codeLiteral('./reference.wav'), codeLiteral('-F prompt_audio=@reference.wav')],
  'docs.moss_clone.ws.location': [codeLiteral('prompt_audio.data')],
  'docs.moss_clone.server.location': [codeLiteral('/app/prompts/reference.wav'), codeLiteral('MOSS_PROMPT_AUDIO_PATH')],
  'docs.moss_clone.warn': [codeLiteral('MOSS_PROMPT_AUDIO_MAX_SECONDS')],
  'docs.moss_http.body': [codeLiteral('POST /api/tts'), codeLiteral('prompt_audio'), codeLiteral('reference_audio')],
  'docs.moss_http.field.model': [codeLiteral('moss')],
  'docs.moss_http.field.voice': [codeLiteral('Junhao')],
  'docs.moss_http.field.format': [codeLiteral('wav'), codeLiteral('pcm'), codeLiteral('mp3'), codeLiteral('ogg_opus/telegram_voice'), codeLiteral('m4a')],
  'docs.moss_ws.body': [codeLiteral('prompt_audio.filename'), codeLiteral('prompt_audio.data'), codeLiteral('data')],
  'docs.moss_ws.note': [codeLiteral('format:"wav"'), codeLiteral('sample_rate'), codeLiteral('channels')],
  'docs.zip.body': [codeLiteral('voice'), codeLiteral('POST /api/tts'), codeLiteral('prompt_text')],
  'docs.zip.warn': [codeLiteral('pcm_s16le'), codeLiteral('wav')],
  'docs.server.body': [codeLiteral('MOSS_PROMPT_AUDIO_PATH')],
  'docs.server.warn': [codeLiteral('models/models--hexgrad--Kokoro-82M-v1.1-zh/voices'), codeLiteral('.pt')],
  'docs.errors.clone.cause': [codeLiteral('kokoro')],
  'docs.errors.clone.fix': [codeLiteral('moss'), codeLiteral('zipvoice')],
  'docs.errors.text.fix': [codeLiteral('3.5')],
  'docs.errors.disabled.cause': [codeLiteral('mp3'), codeLiteral('ogg_opus/telegram_voice'), codeLiteral('m4a')],
  'docs.errors.conversion.cause': [codeLiteral('libopus'), codeLiteral('libmp3lame'), codeLiteral('aac')],
  'docs.errors.conversion.fix': [codeLiteral('wav')],
  'docs.errors.moss.fix': [codeLiteral('/v1/models'), codeLiteral('ANGEVOICE_ENABLED_MODELS'), codeLiteral('MOSS_CUDA_ENABLED')],
  'docs.errors.ws.cause': [codeLiteral('text')],
  'docs.errors.ws.fix': [codeLiteral('ws://host:port/ws/v1/tts')],
  'docs.errors.oom.fix': [codeLiteral('MOSS_PROMPT_AUDIO_MAX_SECONDS')],
  'docs.errors.auth.cause': [codeLiteral('KOKORO_API_KEY')],
  'docs.errors.auth.fix': [codeLiteral('token')],
});

const inline = key => ({ key, fragments: INLINE_FRAGMENTS[key] || [] });
const p = key => ({ type: 'paragraph', content: inline(key) });
const h = key => ({ type: 'heading', content: inline(key) });
const callout = (key, tone = 'info') => ({ type: 'callout', content: inline(key), tone });
const tableCell = value => typeof value === 'string' && value.startsWith('docs.') ? inline(value) : value;
const table = (headers, rows) => ({
  type: 'table',
  headers: headers.map(tableCell),
  rows: rows.map(row => row.map(tableCell)),
});

export const DOCS_CONTENT = Object.freeze({
  nav: [['quick','docs.nav.quick'],['models','docs.nav.models'],['openai','docs.nav.openai'],['moss-clone','docs.nav.moss_clone'],['moss-http','docs.nav.moss_http'],['moss-ws','docs.nav.moss_ws'],['zipvoice-http','docs.nav.zipvoice'],['server-default','docs.nav.server_default'],['errors','docs.nav.errors']],
  sections: [
    { id:'quick', title:'docs.quick.title', blocks:[p('docs.quick.body'),code('quick-health','BASE_URL=http://localhost:8000\n\ncurl "$BASE_URL/health"\ncurl "$BASE_URL/v1/models"\ncurl "$BASE_URL/v1/audio/voices"'),callout('docs.quick.auth')] },
    { id:'models', title:'docs.models.title', blocks:[table(['docs.models.head.id','docs.models.head.use','docs.models.head.clone'],[['docs.models.kokoro.id','docs.models.kokoro.use','docs.models.kokoro.clone'],['docs.models.moss.id','docs.models.moss.use','docs.models.moss.clone'],['docs.models.zip.id','docs.models.zip.use','docs.models.zip.clone']]),callout('docs.models.legacy'),h('docs.models.switch'),code('switch-moss','curl -X POST "$BASE_URL/v1/models/switch" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -d \'{"model":"moss","unload_previous":true}\'')] },
    { id:'openai', title:'docs.openai.title', blocks:[p('docs.openai.body'),code('speech-kokoro','curl -X POST "$BASE_URL/v1/audio/speech" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -d \'{"model":"kokoro","input":"{{docs.example.kokoro}}","voice":"zm_010","speed":1.0,"response_format":"wav"}\' \\\n  --output kokoro.wav'),code('speech-moss','curl -X POST "$BASE_URL/v1/audio/speech" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -d \'{"model":"moss","input":"{{docs.example.moss}}","voice":"Junhao","response_format":"wav"}\' \\\n  --output moss.wav'),code('speech-zipvoice','curl -X POST "$BASE_URL/v1/audio/speech" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -d \'{"model":"zipvoice","input":"{{docs.example.zip}}","voice":"voice_001","response_format":"telegram_voice"}\' \\\n  --output zipvoice.ogg'),callout('docs.openai.ffmpeg')] },
    { id:'moss-clone', title:'docs.moss_clone.title', blocks:[p('docs.moss_clone.body'),table(['docs.moss_clone.head.method','docs.moss_clone.head.location','docs.moss_clone.head.use'],[['docs.moss_clone.http.method','docs.moss_clone.http.location','docs.moss_clone.http.use'],['docs.moss_clone.ws.method','docs.moss_clone.ws.location','docs.moss_clone.ws.use'],['docs.moss_clone.server.method','docs.moss_clone.server.location','docs.moss_clone.server.use']]),callout('docs.moss_clone.warn','warn')] },
    { id:'moss-http', title:'docs.moss_http.title', blocks:[p('docs.moss_http.body'),code('moss-http-curl','BASE_URL=http://localhost:8000\n\ncurl -X POST "$BASE_URL/api/tts" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -F model=moss \\\n  -F text="{{docs.example.clone}}" \\\n  -F voice=Junhao \\\n  -F response_format=wav \\\n  -F prompt_audio=@reference.wav \\\n  --output clone.wav'),h('docs.moss_http.fields'),table(['docs.moss_http.head.field','docs.moss_http.head.description'],[['model','docs.moss_http.field.model'],['text','docs.moss_http.field.text'],['voice','docs.moss_http.field.voice'],['response_format','docs.moss_http.field.format'],['prompt_audio','docs.moss_http.field.audio']]),h('docs.moss_http.python'),code('moss-http-python','import requests\n\nbase_url = "http://localhost:8000"\nheaders = {"Authorization": "Bearer YOUR_TOKEN"}\n\nwith open("reference.wav", "rb") as audio:\n    files = {"prompt_audio": ("reference.wav", audio, "audio/wav")}\n    data = {\n        "model": "moss",\n        "text": "{{docs.example.python_clone}}",\n        "voice": "Junhao",\n        "response_format": "wav",\n    }\n    resp = requests.post(f"{base_url}/api/tts", headers=headers, data=data, files=files)\n    resp.raise_for_status()\n\nwith open("clone.wav", "wb") as out:\n    out.write(resp.content)')] },
    { id:'moss-ws', title:'docs.moss_ws.title', blocks:[p('docs.moss_ws.body'),h('docs.moss_ws.first'),code('moss-ws-json','{\n  "model": "moss",\n  "text": "{{docs.example.ws_clone}}",\n  "voice": "Junhao",\n  "format": "pcm_s16le",\n  "binary": false,\n  "prompt_audio": {\n    "filename": "reference.wav",\n    "data": "<base64-or-data-url>"\n  },\n  "token": "YOUR_TOKEN"\n}'),h('docs.moss_ws.browser'),code('moss-ws-browser','async function fileToDataUrl(file) {\n  return await new Promise((resolve, reject) => {\n    const reader = new FileReader();\n    reader.onload = () => resolve(reader.result);\n    reader.onerror = reject;\n    reader.readAsDataURL(file);\n  });\n}\n\nasync function startMossCloneStream(file) {\n  const promptData = await fileToDataUrl(file);\n  const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");\n\n  ws.onopen = () => {\n    ws.send(JSON.stringify({\n      model: "moss", text: "{{docs.example.browser_clone}}", voice: "Junhao",\n      format: "pcm_s16le", binary: false, token: "YOUR_TOKEN",\n      prompt_audio: {filename: file.name || "reference.wav", data: promptData}\n    }));\n  };\n\n  ws.onmessage = (event) => {\n    const msg = JSON.parse(event.data);\n    if (msg.type === "started") {\n      console.log("stream started", msg);\n    }\n    if (msg.type === "audio") {\n      const bytes = Uint8Array.from(atob(msg.data), c => c.charCodeAt(0));\n      // {{docs.example.browser_comment}}\n      console.log("audio chunk", bytes.byteLength);\n    }\n    if (msg.type === "done") {\n      ws.close();\n    }\n    if (msg.type === "error" || msg.type === "segment_error") {\n      console.error(msg.message);\n    }\n  };\n\n  return ws;\n}'),h('docs.moss_ws.python'),code('moss-ws-python','import asyncio\nimport base64\nimport json\nimport websockets\n\nasync def main():\n    with open("reference.wav", "rb") as f:\n        prompt_b64 = base64.b64encode(f.read()).decode("ascii")\n\n    async with websockets.connect("ws://localhost:8000/ws/v1/tts") as ws:\n        await ws.send(json.dumps({\n            "model": "moss", "text": "{{docs.example.python_ws}}", "voice": "Junhao",\n            "format": "pcm_s16le", "binary": False, "token": "YOUR_TOKEN",\n            "prompt_audio": {"filename": "reference.wav", "data": prompt_b64}\n        }, ensure_ascii=False))\n\n        with open("stream.pcm", "wb") as out:\n            async for raw in ws:\n                msg = json.loads(raw)\n                if msg.get("type") == "audio":\n                    out.write(base64.b64decode(msg["data"]))\n                elif msg.get("type") in {"done", "cancelled"}:\n                    break\n                elif msg.get("type") in {"error", "segment_error"}:\n                    raise RuntimeError(msg.get("message"))\n\nasyncio.run(main())'),callout('docs.moss_ws.note')] },
    { id: 'zipvoice-http', title:'docs.zip.title', blocks:[p('docs.zip.body'),code('zipvoice-reference','curl -X POST "$BASE_URL/api/tts" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -F model=zipvoice \\\n  -F text="{{docs.example.zip_clone}}" \\\n  -F voice=voice_001 \\\n  -F prompt_text="{{docs.example.prompt}}" \\\n  -F prompt_audio=@reference.wav \\\n  -F response_format=wav \\\n  --output zipvoice.wav'),code('zipvoice-telegram','curl -X POST "$BASE_URL/api/tts" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -F model=zipvoice \\\n  -F text="{{docs.example.telegram}}" \\\n  -F voice=voice_001 \\\n  -F response_format=telegram_voice \\\n  --output voice.ogg'),callout('docs.zip.warn','warn')] },
    { id:'server-default', title:'docs.server.title', blocks:[p('docs.server.body'),h('docs.server.compose'),code('server-compose','volumes:\n  - ../../prompts:/app/prompts:ro\n\nenvironment:\n  - MOSS_PROMPT_AUDIO_PATH=/app/prompts/reference.wav\n  - MOSS_PROMPT_AUDIO_MAX_SECONDS=8\n  - MOSS_PROMPT_CACHE_MAX_ITEMS=8'),h('docs.server.call'),code('server-default-curl','curl -X POST "$BASE_URL/api/tts" \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -F model=moss \\\n  -F text="{{docs.example.default_clone}}" \\\n  -F voice=Junhao \\\n  -F response_format=wav \\\n  --output clone-default.wav'),callout('docs.server.warn','warn')] },
    { id:'errors', title:'docs.errors.title', blocks:[table(['docs.errors.head.symptom','docs.errors.head.cause','docs.errors.head.fix'],[['docs.errors.clone.symptom','docs.errors.clone.cause','docs.errors.clone.fix'],['docs.errors.text.symptom','docs.errors.text.cause','docs.errors.text.fix'],['FFMPEG_DISABLED','docs.errors.disabled.cause','docs.errors.disabled.fix'],['FFMPEG_UNAVAILABLE','docs.errors.unavailable.cause','docs.errors.unavailable.fix'],['FFMPEG_CONVERSION_FAILED','docs.errors.conversion.cause','docs.errors.conversion.fix'],['docs.errors.moss.symptom','docs.errors.moss.cause','docs.errors.moss.fix'],['docs.errors.ws.symptom','docs.errors.ws.cause','docs.errors.ws.fix'],['docs.errors.oom.symptom','docs.errors.oom.cause','docs.errors.oom.fix'],['401 Unauthorized','docs.errors.auth.cause','docs.errors.auth.fix']])] }
  ]
});

export const DOCS_SHELL_KEYS = Object.freeze([
  'docs.page.title',
  'docs.hero.eyebrow',
  'docs.hero.title',
  'docs.hero.desc',
  'docs.link.studio',
  'docs.link.swagger',
  'docs.link.redoc',
  'docs.link.health',
]);

export const DOCS_SHELL_INLINE_CONTENT = Object.freeze({
  'docs-hero-description': inline('docs.hero.desc'),
});

export const DOCS_DYNAMIC_KEYS = Object.freeze([
  'docs.auth.required',
  'docs.auth.open',
  'docs.copy.idle',
  'docs.copy.success',
  'docs.copy.failure',
  'docs.nav.aria',
]);

export const INLINE_FRAGMENT_TYPES = Object.freeze(['text', 'code', 'strong', 'link']);

export function collectDocsTranslationKeys(content = DOCS_CONTENT) {
  const keys = new Set(DOCS_DYNAMIC_KEYS);
  const visit = value => { if (typeof value === 'string') { if (value.startsWith('docs.')) keys.add(value); return; } if (!value || typeof value !== 'object') return; if (Array.isArray(value)) return value.forEach(visit); Object.values(value).forEach(visit); };
  visit(content); for (const value of JSON.stringify(content).matchAll(/\{\{(docs\.[\w.]+)\}\}/g)) keys.add(value[1]); return keys;
}
