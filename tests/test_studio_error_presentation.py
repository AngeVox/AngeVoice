from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
MODULE = PACKAGE_ROOT / "static" / "studio" / "error-presentation.js"
APP = PACKAGE_ROOT / "static" / "app.js"


def _node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


NODE_POLICY = f"""
import {{ createErrorPresentationPolicy }} from {json.dumps(MODULE.as_uri())};
const rawPattern = /integer division|ZeroDivisionError|Traceback|TypeError:|ValueError:|tokens_lens|No English or Chinese characters/i;
const known = new Map([
  ['KNOWN', 'mapped-known'],
  ['FIRST', 'mapped-first'],
  ['SECOND', 'mapped-second'],
  ['THIRD', 'mapped-third'],
]);
const policy = createErrorPresentationPolicy({{
  resolveKnownCode: code => known.get(code),
  isRawBackendError: message => rawPattern.test(String(message || '')),
}});
const present = (payload, options = {{}}) => policy.present(payload, {{
  fallback: 'ordinary-fallback',
  rawFallback: 'raw-fallback',
  ...options,
}});
"""


def test_module_is_pure_native_esm_and_validates_dependencies() -> None:
    result = _node(
        f"""
        for (const name of ['window', 'document', 'fetch']) {{
          Object.defineProperty(globalThis, name, {{
            configurable: true,
            get() {{ throw new Error(`import touched ${{name}}`); }},
          }});
        }}
        const module = await import({json.dumps(MODULE.as_uri())});
        const errors = [];
        for (const dependencies of [{{}}, {{ resolveKnownCode() {{}} }}]) {{
          try {{ module.createErrorPresentationPolicy(dependencies); }}
          catch (error) {{ errors.push(error.name); }}
        }}
        console.log(JSON.stringify({{
          exports: Object.keys(module),
          errors,
        }}));
        """
    )
    assert result == {
        "exports": ["createErrorPresentationPolicy"],
        "errors": ["TypeError", "TypeError"],
    }
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("window", "document", "fetch(", "i18n", "app.js", "USER_ERROR_MESSAGES"):
        assert forbidden not in source
    assert not re.search(r"[\u3400-\u9fff]", source)


def test_code_and_message_precedence_matrix() -> None:
    result = _node(
        f"""
        {NODE_POLICY}
        const codeCases = {{
          code: present({{ code: 'FIRST' }}),
          errorCode: present({{ error_code: 'SECOND' }}),
          detailCode: present({{ detail: {{ code: 'THIRD' }} }}),
          allCodes: present({{ code: 'FIRST', error_code: 'SECOND', detail: {{ code: 'THIRD' }} }}),
          emptyCodeContinues: present({{ code: '', error_code: 'SECOND', detail: {{ code: 'THIRD' }} }}),
          knownWithMessage: present({{ code: 'KNOWN', message: 'backend business message' }}),
          unknownWithMessage: present({{ code: 'UNKNOWN', message: 'backend business message' }}),
          unknownWithoutMessage: present({{ code: 'UNKNOWN' }}),
        }};
        const messageCases = {{
          message: present({{ message: 'root-message' }}),
          detailMessage: present({{ detail: {{ message: 'detail-message' }} }}),
          stringDetail: present({{ detail: 'string-detail' }}),
          error: present({{ error: 'error-field' }}),
          allMessages: present({{ message: 'root-message', detail: {{ message: 'detail-message' }}, error: 'error-field' }}),
          emptyContinues: present({{ message: '', detail: {{ message: 'detail-message' }}, error: 'error-field' }}),
          nonStringContinues: present({{ message: {{ unsafe: true }}, detail: {{ message: 7 }}, error: 'error-field' }}),
          noObjectStringification: present({{ message: {{}}, detail: {{ message: [] }}, error: 9 }}),
        }};
        console.log(JSON.stringify({{ codeCases, messageCases }}));
        """
    )

    codes = result["codeCases"]
    assert codes["code"]["code"] == "FIRST"
    assert codes["errorCode"]["code"] == "SECOND"
    assert codes["detailCode"]["code"] == "THIRD"
    assert codes["allCodes"]["code"] == "FIRST"
    assert codes["emptyCodeContinues"]["code"] == "SECOND"
    assert codes["knownWithMessage"] == {
        "value": "mapped-known",
        "source": "known_code",
        "code": "KNOWN",
        "backendMessage": "backend business message",
        "rawBackend": False,
    }
    assert codes["unknownWithMessage"]["source"] == "backend_message"
    assert codes["unknownWithMessage"]["value"] == "backend business message"
    assert codes["unknownWithoutMessage"]["source"] == "fallback"
    assert codes["unknownWithoutMessage"]["code"] == "UNKNOWN"

    messages = result["messageCases"]
    assert messages["message"]["value"] == "root-message"
    assert messages["detailMessage"]["value"] == "detail-message"
    assert messages["stringDetail"]["value"] == "string-detail"
    assert messages["error"]["value"] == "error-field"
    assert messages["allMessages"]["value"] == "root-message"
    assert messages["emptyContinues"]["value"] == "detail-message"
    assert messages["nonStringContinues"]["value"] == "error-field"
    assert messages["noObjectStringification"]["value"] == "ordinary-fallback"
    assert "[object Object]" not in json.dumps(result)


def test_app_style_own_property_resolver_rejects_prototype_chain_codes() -> None:
    result = _node(
        f"""
        import {{ createErrorPresentationPolicy }} from {json.dumps(MODULE.as_uri())};
        const messages = {{
          NO_SYNTHESIZABLE_TEXT: 'no-text',
          FFMPEG_DISABLED: 'disabled',
          FFMPEG_UNAVAILABLE: 'unavailable',
          FFMPEG_CONVERSION_FAILED: 'conversion-failed',
        }};
        const policy = createErrorPresentationPolicy({{
          resolveKnownCode: code => (
            Object.prototype.hasOwnProperty.call(messages, code)
              ? messages[code]
              : undefined
          ),
          isRawBackendError: () => false,
        }});
        const present = payload => policy.present(payload, {{ fallback: 'ordinary-fallback' }});
        const prototypeCodes = ['constructor', 'toString', 'valueOf', '__proto__'];
        const prototypeMatrix = Object.fromEntries(prototypeCodes.map(code => [code, {{
          withMessage: present({{ code, message: `backend-${{code}}` }}),
          withoutMessage: present({{ code }}),
        }}]));
        const ownCodes = Object.fromEntries(Object.keys(messages).map(code => [
          code,
          present({{ code, message: 'backend-must-not-win' }}),
        ]));
        console.log(JSON.stringify({{ prototypeMatrix, ownCodes }}));
        """
    )

    for code, cases in result["prototypeMatrix"].items():
        assert cases["withMessage"] == {
            "value": f"backend-{code}",
            "source": "backend_message",
            "code": code,
            "backendMessage": f"backend-{code}",
            "rawBackend": False,
        }
        assert cases["withoutMessage"] == {
            "value": "ordinary-fallback",
            "source": "fallback",
            "code": code,
            "backendMessage": "",
            "rawBackend": False,
        }

    assert {code: value["value"] for code, value in result["ownCodes"].items()} == {
        "NO_SYNTHESIZABLE_TEXT": "no-text",
        "FFMPEG_DISABLED": "disabled",
        "FFMPEG_UNAVAILABLE": "unavailable",
        "FFMPEG_CONVERSION_FAILED": "conversion-failed",
    }
    assert all(value["source"] == "known_code" for value in result["ownCodes"].values())


def test_raw_backend_pattern_matrix_and_semantic_fallbacks() -> None:
    result = _node(
        f"""
        {NODE_POLICY}
        const patterns = [
          'integer division', 'ZeroDivisionError', 'Traceback', 'TypeError:',
          'ValueError:', 'tokens_lens', 'No English or Chinese characters',
        ];
        const exact = patterns.map(message => present({{ message }}));
        const caseInsensitive = present({{ message: 'tRaCeBaCk FROM SERVICE' }});
        const nearMisses = [
          'division by integer', 'Zero Division Error', 'Trace back', 'Type Error:',
          'Value Error:', 'tokens lens', 'English or Chinese characters',
          'error', 'exception', 'failed',
        ].map(message => present({{ message }}));
        const knownWithTraceback = present({{ code: 'KNOWN', message: 'Traceback: private stack' }});
        const streamRaw = present({{ message: 'Traceback: private stack' }}, {{
          fallback: 'stream-fallback', rawFallback: 'stream-safe',
        }});
        const nonStreamRaw = present({{ message: 'TypeError: private stack' }});
        const playbackRaw = present({{ message: 'ValueError: playback stack' }}, {{
          fallback: 'playback-fallback', rawFallback: 'raw-fallback',
        }});
        console.log(JSON.stringify({{
          patterns, exact, caseInsensitive, nearMisses, knownWithTraceback,
          streamRaw, nonStreamRaw, playbackRaw,
        }}));
        """
    )
    assert result["patterns"] == [
        "integer division",
        "ZeroDivisionError",
        "Traceback",
        "TypeError:",
        "ValueError:",
        "tokens_lens",
        "No English or Chinese characters",
    ]
    assert all(item["source"] == "raw_backend_fallback" for item in result["exact"])
    assert all(item["rawBackend"] is True for item in result["exact"])
    assert result["caseInsensitive"]["source"] == "raw_backend_fallback"
    assert all(item["source"] == "backend_message" for item in result["nearMisses"])
    assert result["knownWithTraceback"] == {
        "value": "mapped-known",
        "source": "known_code",
        "code": "KNOWN",
        "backendMessage": "Traceback: private stack",
        "rawBackend": True,
    }
    assert result["streamRaw"]["value"] == "stream-safe"
    assert result["nonStreamRaw"]["value"] == "raw-fallback"
    assert result["playbackRaw"]["value"] == "raw-fallback"


def test_payload_shapes_metadata_freezing_descriptors_and_input_immutability() -> None:
    result = _node(
        f"""
        {NODE_POLICY}
        const shapes = {{
          null: present(null),
          undefined: present(undefined),
          number: present(42),
          string: present('literal payload'),
          array: present(['array payload']),
          boolean: present(true),
          error: present(new Error('native-error-message')),
          object: present({{ message: 'object-message' }}),
          detailArray: present({{ detail: [{{ message: 'unsafe' }}] }}),
          detailNull: present({{ detail: null }}),
        }};
        const frozenPayload = Object.freeze({{
          code: '',
          error_code: 'UNKNOWN',
          detail: Object.freeze({{ message: 'frozen-message' }}),
        }});
        const frozenResult = present(frozenPayload);
        const descriptor = {{ key: 'future.error', params: {{ count: 1 }} }};
        const descriptorPolicy = createErrorPresentationPolicy({{
          resolveKnownCode: code => code === 'DESCRIPTOR' ? descriptor : undefined,
          isRawBackendError: () => false,
        }});
        const descriptorResult = descriptorPolicy.present({{ code: 'DESCRIPTOR' }}, {{ fallback: 'fallback' }});
        let mutationBlocked = false;
        try {{ frozenResult.source = 'changed'; }} catch (_) {{ mutationBlocked = true; }}
        console.log(JSON.stringify({{
          shapes, frozenResult, resultFrozen: Object.isFrozen(frozenResult), mutationBlocked,
          inputStillFrozen: Object.isFrozen(frozenPayload) && Object.isFrozen(frozenPayload.detail),
          descriptorIdentity: descriptorResult.value === descriptor,
          descriptorValueType: typeof descriptorResult.value,
          descriptorSource: descriptorResult.source,
        }}));
        """
    )
    shapes = result["shapes"]
    for name in ("null", "undefined", "number", "string", "array", "boolean", "detailArray", "detailNull"):
        assert shapes[name]["source"] == "fallback"
    assert shapes["error"]["value"] == "native-error-message"
    assert shapes["object"]["value"] == "object-message"
    assert result["frozenResult"]["code"] == "UNKNOWN"
    assert result["frozenResult"]["backendMessage"] == "frozen-message"
    assert result["resultFrozen"] is True
    assert result["mutationBlocked"] is True
    assert result["inputStillFrozen"] is True
    assert result["descriptorIdentity"] is True
    assert result["descriptorValueType"] == "object"
    assert result["descriptorSource"] == "known_code"


def test_response_parsing_matrix_reads_body_once_and_classifies_transport_fallback() -> None:
    result = _node(
        f"""
        {NODE_POLICY}
        function response(payload, {{ statusText = '', reject = false }} = {{}}) {{
          let reads = 0;
          return {{
            statusText,
            get reads() {{ return reads; }},
            json() {{
              reads += 1;
              return reject ? Promise.reject(new SyntaxError('invalid json')) : Promise.resolve(payload);
            }},
          }};
        }}
        async function read(payload, options = {{}}) {{
          const fake = response(payload, options);
          const value = await policy.readResponseError(fake, {{
            fallback: 'request-fallback', rawFallback: 'raw-fallback',
          }});
          return {{ value, reads: fake.reads }};
        }}
        const cases = {{
          object: await read({{ message: 'body-message' }}, {{ statusText: 'Bad Request' }}),
          nullJson: await read(null, {{ statusText: 'Bad Request' }}),
          stringJson: await read('string-json', {{ statusText: 'Bad Request' }}),
          arrayJson: await read([{{ message: 'array-message' }}], {{ statusText: 'Bad Request' }}),
          invalidJson: await read(undefined, {{ statusText: 'Bad Request', reject: true }}),
          emptyStatus: await read(null),
          statusOnly: await read({{}}, {{ statusText: 'Service Unavailable' }}),
          bodyBeforeStatus: await read({{ detail: 'body-detail' }}, {{ statusText: 'Conflict' }}),
          knownCode: await read({{ error_code: 'KNOWN', message: 'backend' }}, {{ statusText: 'Bad Request' }}),
          rawBody: await read({{ message: 'Traceback: private' }}, {{ statusText: 'Bad Request' }}),
          detailObject: await read({{ detail: {{ message: 'nested-message' }} }}),
          detailString: await read({{ detail: 'detail-string' }}),
        }};
        console.log(JSON.stringify(cases));
        """
    )
    assert all(case["reads"] == 1 for case in result.values())
    assert result["object"]["value"]["source"] == "backend_message"
    assert result["object"]["value"]["value"] == "body-message"
    for name in ("nullJson", "stringJson", "arrayJson", "invalidJson", "statusOnly"):
        assert result[name]["value"]["source"] == "transport_status"
    assert result["emptyStatus"]["value"]["source"] == "fallback"
    assert result["emptyStatus"]["value"]["value"] == "request-fallback"
    assert result["bodyBeforeStatus"]["value"]["value"] == "body-detail"
    assert result["knownCode"]["value"]["source"] == "known_code"
    assert result["rawBody"]["value"]["source"] == "raw_backend_fallback"
    assert result["detailObject"]["value"]["value"] == "nested-message"
    assert result["detailString"]["value"]["value"] == "detail-string"


def test_response_json_rejection_skips_policy_callbacks_and_reads_once() -> None:
    result = _node(
        f"""
        import {{ createErrorPresentationPolicy }} from {json.dumps(MODULE.as_uri())};
        let resolverCalls = 0;
        let detectorCalls = 0;
        let reads = 0;
        const policy = createErrorPresentationPolicy({{
          resolveKnownCode() {{ resolverCalls += 1; }},
          isRawBackendError() {{ detectorCalls += 1; }},
        }});
        const response = {{
          statusText: 'Bad Gateway',
          json() {{
            reads += 1;
            return Promise.reject(new SyntaxError('invalid json'));
          }},
        }};
        const value = await policy.readResponseError(response, {{ fallback: 'request-fallback' }});
        console.log(JSON.stringify({{ value, reads, resolverCalls, detectorCalls }}));
        """
    )
    assert result == {
        "value": {
            "value": "Bad Gateway",
            "source": "transport_status",
            "code": "",
            "backendMessage": "",
            "rawBackend": False,
        },
        "reads": 1,
        "resolverCalls": 0,
        "detectorCalls": 0,
    }


def test_response_policy_does_not_swallow_resolver_or_detector_exceptions() -> None:
    result = _node(
        f"""
        import {{ createErrorPresentationPolicy }} from {json.dumps(MODULE.as_uri())};
        const response = payload => ({{
          statusText: 'Transport status must not win',
          reads: 0,
          json() {{ this.reads += 1; return Promise.resolve(payload); }},
        }});
        const resolverResponse = response({{ code: 'KNOWN' }});
        const resolverPolicy = createErrorPresentationPolicy({{
          resolveKnownCode() {{ throw new Error('resolver failure'); }},
          isRawBackendError: () => false,
        }});
        const detectorResponse = response({{ message: 'backend message' }});
        const detectorPolicy = createErrorPresentationPolicy({{
          resolveKnownCode: () => undefined,
          isRawBackendError() {{ throw new Error('detector failure'); }},
        }});
        const errors = {{}};
        try {{ await resolverPolicy.readResponseError(resolverResponse, {{ fallback: 'fallback' }}); }}
        catch (error) {{ errors.resolver = error.message; }}
        try {{ await detectorPolicy.readResponseError(detectorResponse, {{ fallback: 'fallback' }}); }}
        catch (error) {{ errors.detector = error.message; }}
        await new Promise(resolve => setImmediate(resolve));
        console.log(JSON.stringify({{
          errors,
          resolverReads: resolverResponse.reads,
          detectorReads: detectorResponse.reads,
        }}));
        """
    )
    assert result == {
        "errors": {"resolver": "resolver failure", "detector": "detector failure"},
        "resolverReads": 1,
        "detectorReads": 1,
    }


def test_descriptor_values_survive_known_raw_and_response_fallback_paths() -> None:
    result = _node(
        f"""
        import {{ createErrorPresentationPolicy }} from {json.dumps(MODULE.as_uri())};
        const known = {{ key: 'studio.error.ffmpeg_disabled', params: null }};
        const raw = {{ key: 'studio.error.synthesis_safe_fallback', params: null }};
        const fallback = {{ key: 'studio.error.request_failed', params: null }};
        const policy = createErrorPresentationPolicy({{
          resolveKnownCode: code => code === 'KNOWN' ? known : undefined,
          isRawBackendError: message => /Traceback/.test(message),
        }});
        const knownResult = policy.present(
          {{ code: 'KNOWN', message: 'backend must not win' }},
          {{ fallback, rawFallback: raw }},
        );
        const rawResult = policy.present(
          {{ message: 'Traceback: private' }},
          {{ fallback, rawFallback: raw }},
        );
        const backendResult = policy.present(
          {{ code: 'UNKNOWN', message: 'backend literal' }},
          {{ fallback, rawFallback: raw }},
        );
        let emptyReads = 0;
        const emptyStatusResult = await policy.readResponseError({{
          statusText: '',
          json() {{ emptyReads += 1; return Promise.reject(new SyntaxError('invalid')); }},
        }}, {{ fallback, rawFallback: raw }});
        let statusReads = 0;
        const statusResult = await policy.readResponseError({{
          statusText: 'Gateway Failure',
          json() {{ statusReads += 1; return Promise.reject(new SyntaxError('invalid')); }},
        }}, {{ fallback, rawFallback: raw }});
        console.log(JSON.stringify({{
          knownIdentity: knownResult.value === known,
          rawIdentity: rawResult.value === raw,
          fallbackIdentity: emptyStatusResult.value === fallback,
          knownResult, rawResult, backendResult, emptyStatusResult, statusResult,
          emptyReads, statusReads,
          frozen: [knownResult, rawResult, backendResult, emptyStatusResult, statusResult].every(Object.isFrozen),
        }}));
        """
    )
    assert result["knownIdentity"] is True
    assert result["rawIdentity"] is True
    assert result["fallbackIdentity"] is True
    assert result["knownResult"]["source"] == "known_code"
    assert result["knownResult"]["backendMessage"] == "backend must not win"
    assert result["rawResult"]["source"] == "raw_backend_fallback"
    assert result["backendResult"]["value"] == "backend literal"
    assert result["backendResult"]["source"] == "backend_message"
    assert result["emptyStatusResult"]["value"]["key"] == "studio.error.request_failed"
    assert result["emptyStatusResult"]["source"] == "fallback"
    assert result["statusResult"]["value"] == "Gateway Failure"
    assert result["statusResult"]["source"] == "transport_status"
    assert result["emptyReads"] == result["statusReads"] == 1
    assert result["frozen"] is True


def test_app_composes_descriptor_policy_display_boundary_and_text_content_sink() -> None:
    app = APP.read_text(encoding="utf-8")
    assert "import { createErrorPresentationPolicy } from './studio/error-presentation.js';" in app
    assert "Object.prototype.hasOwnProperty.call(USER_ERROR_MESSAGES, code)" in app
    assert "isRawBackendError: looksLikeRawBackendError" in app
    assert "function userFacingErrorPresentation(" in app
    assert "fallback = descriptor('studio.error.request_failed')" in app
    assert "rawFallback: USER_ERROR_MESSAGES.NO_SYNTHESIZABLE_TEXT" in app
    assert "return errorPresentationPolicy.present(payload, { fallback, rawFallback });" in app
    display = re.search(
        r"function showErrorPresentation\(presentation, options = \{\}\) \{(?P<body>.*?)\n\}",
        app,
        re.DOTALL,
    )
    assert display
    assert "setTranslatedDescriptor(value, true, options)" in display.group("body")
    assert "setProgress(typeof value === 'string' ? value : '', true, options)" in display.group("body")
    read_error = re.search(
        r"async function readError\(response\) \{(?P<body>.*?)\n\}", app, re.DOTALL
    )
    assert read_error
    assert "errorPresentationPolicy.readResponseError(response" in read_error.group("body")
    assert "fallback: descriptor('studio.error.request_failed')" in read_error.group("body")
    assert "rawFallback: DEFAULT_RAW_BACKEND_FALLBACK" in read_error.group("body")
    assert ".json()" not in read_error.group("body")
    assert app.count("readError: readErrorText") == 2
    assert "reader.onerror = () => reject(reader.error || new Error());" in app
    assert "onAuthRequired: () => {" in app
    assert "onSessionInvalid: () => {" in app
    assert app.count("els.settingsDialog.showModal();") >= 3
    progress = re.search(r"function setProgress\([^)]*\) \{(?P<body>.*?)\n\}", app, re.DOTALL)
    assert progress
    assert "els.progress.textContent = text" in progress.group("body")
    assert "innerHTML" not in progress.group("body")
    assert "insertAdjacentHTML" not in progress.group("body")


def test_known_error_map_uses_exact_descriptor_keys_and_raw_pattern_is_compatible() -> None:
    app = APP.read_text(encoding="utf-8")
    expected_keys = {
        "NO_SYNTHESIZABLE_TEXT": "studio.error.no_synthesizable_text",
        "FFMPEG_DISABLED": "studio.error.ffmpeg_disabled",
        "FFMPEG_UNAVAILABLE": "studio.error.ffmpeg_unavailable",
        "FFMPEG_CONVERSION_FAILED": "studio.error.ffmpeg_conversion_failed",
    }
    for code, key in expected_keys.items():
        assert f"{code}: descriptor('{key}')" in app
    assert "const DEFAULT_RAW_BACKEND_FALLBACK = descriptor('studio.error.synthesis_safe_fallback');" in app
    assert (
        "/integer division|ZeroDivisionError|Traceback|TypeError:|ValueError:|tokens_lens|No English or Chinese characters/i"
        in app
    )
    assert "|error|exception|failed" not in app
