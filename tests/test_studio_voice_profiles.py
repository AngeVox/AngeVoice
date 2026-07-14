from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "voice-profiles.js"


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
  constructor(value = '') {
    this.value = value;
    this.disabled = false;
    this.hidden = true;
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.classList = { values: new Set(), toggle: (name, enabled) => enabled ? this.classList.values.add(name) : this.classList.values.delete(name) };
  }
  get childElementCount() { return this.children.length; }
  set innerHTML(_) { this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name, callback) { if (this.listeners.get(name) === callback) this.listeners.delete(name); }
  fire(name) { this.listeners.get(name)?.({ target: this }); }
}
const fakeDocument = { createElement: () => new FakeElement() };
"""


def test_voice_profile_controller_owns_profiles_signature_selection_and_copy_only_rendering() -> None:
    result = _node(
        f"""
        import {{ createVoiceProfileController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        let selected = 'one';
        let listCalls = 0;
        let renderCalls = 0;
        const events = [];
        const timers = [];
        const elements = {{
          profileSelect: new FakeElement(), profileId: new FakeElement('draft-id'), profileName: new FakeElement('Draft name'),
          promptText: new FakeElement('draft reference'), recommendedPrompts: new FakeElement(), recommendButton: new FakeElement(),
          saveButton: new FakeElement(), updateButton: new FakeElement(), deleteButton: new FakeElement(),
        }};
        const controller = createVoiceProfileController({{
          elements,
              requests: {{
                list: async () => {{ listCalls += 1; return new Response(JSON.stringify({{ profiles: [{{ voice_id: 'one', name: 'One', revision: 'r1' }}, {{ voice_id: 'two', name: 'Two', revision: 'r2' }}] }})); }},
                delete: async () => new Response(JSON.stringify({{ deleted: true }})),
          }},
          callbacks: {{
            supportsProfiles: () => true, currentEngineId: () => 'zipvoice', getSelectedVoice: () => selected,
            setSelectedVoice: value => {{ selected = value; }}, getPromptAudioFile: () => ({{ name: 'ref.wav' }}),
            onProfilesChanged: value => {{ renderCalls += 1; events.push(['profiles', value.selectedVoice, value.changed]); }},
            onSelection: value => events.push(['selected', value]),
            onProgress: copy => events.push(['progress', copy.key]),
          }},
          translate: key => `t:${{key}}`,
          environment: {{ document: fakeDocument, setTimeout: callback => {{ timers.push(callback); return timers.length; }}, clearTimeout: timer => events.push(['cancelTimer', timer]) }},
        }});
        const first = await controller.load();
        const second = await controller.load();
        controller.selectVoice('two');
        await controller.remove();
        const confirmationBeforeCopy = controller.deleteConfirmation;
        controller.renderCopy();
        const preserved = {{ id: elements.profileId.value, name: elements.profileName.value, prompt: elements.promptText.value, confirmation: controller.deleteConfirmation }};
        controller.selectVoice('one');
        const confirmationAfterSelection = controller.deleteConfirmation;
        controller.dispose();
        console.log(JSON.stringify({{
          first, second, listCalls, renderCalls, selected, display: controller.displayName('two'), signature: controller.signature,
          selectOptions: elements.profileSelect.children.map(option => [option.value, option.textContent]),
          confirmationBeforeCopy, preserved, confirmationAfterSelection, listenersAfterDispose: [...elements.profileSelect.listeners, ...elements.deleteButton.listeners].length,
          cancelledTimers: events.filter(event => event[0] === 'cancelTimer').length,
        }}));
        """
    )
    assert result["first"] is True
    assert result["second"] is True
    assert result["listCalls"] == 2
    assert result["renderCalls"] == 1
    assert result["selected"] == "one"
    assert result["display"] == "Two"
    assert result["selectOptions"] == [["", "t:profile.temporary_clone_uploaded"], ["one", "One"], ["two", "Two"]]
    assert result["confirmationBeforeCopy"] == result["preserved"]["confirmation"] == "two"
    assert result["preserved"] == {"id": "draft-id", "name": "Two", "prompt": "draft reference", "confirmation": "two"}
    assert result["confirmationAfterSelection"] == ""
    assert result["listenersAfterDispose"] == 0
    assert result["cancelledTimers"] >= 1


def test_voice_profile_controller_validates_and_serializes_save_update_and_two_step_delete() -> None:
    result = _node(
        f"""
        import {{ createVoiceProfileController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        let selected = '';
        let profiles = [];
        let saves = 0;
        let updates = 0;
        let deletes = 0;
        let deleteFails = true;
        const progress = [];
        const selections = [];
        const elements = {{
          profileSelect: new FakeElement(), profileId: new FakeElement(''), profileName: new FakeElement('My voice'),
          promptText: new FakeElement('reference text'), recommendedPrompts: new FakeElement(), recommendButton: new FakeElement(),
          saveButton: new FakeElement(), updateButton: new FakeElement(), deleteButton: new FakeElement(),
        }};
        const controller = createVoiceProfileController({{
          elements,
          requests: {{
            list: async () => new Response(JSON.stringify({{ profiles }})),
            save: async values => {{ saves += 1; profiles = [{{ voice_id: values.voiceId, name: values.name, revision: 'r1' }}]; return new Response(JSON.stringify({{ profile: profiles[0] }})); }},
            update: async values => {{ updates += 1; profiles = [{{ ...profiles[0], name: values.name, revision: 'r2' }}]; return new Response(JSON.stringify({{ profile: profiles[0] }})); }},
                delete: async () => {{ deletes += 1; if (deleteFails) return new Response('blocked', {{ status: 409 }}); profiles = []; return new Response(JSON.stringify({{ deleted: true }})); }},
            readError: async response => response.status === 409 ? 'blocked by fixture' : '',
          }},
          callbacks: {{
            supportsProfiles: () => true, currentEngineId: () => 'zipvoice', getSelectedVoice: () => selected,
            setSelectedVoice: value => {{ selected = value; }}, getPromptAudioFile: () => ({{ name: 'reference.wav' }}),
            onProfilesChanged: () => {{}}, onSelection: value => selections.push(value),
            onProgress: (copy, error) => progress.push([copy.key, Boolean(error)]),
            onError: (error, copy) => progress.push([copy.key, String(error.message || '')]),
          }},
          translate: key => key,
          environment: {{ document: fakeDocument, setTimeout: () => 1, clearTimeout: () => {{}} }},
        }});
        const missing = await controller.save();
        elements.profileId.value = 'voice_001';
        elements.promptText.value = '';
        const missingPrompt = await controller.save();
        elements.promptText.value = 'reference text';
        const saved = await Promise.all([controller.save(), controller.save()]);
        elements.profileName.value = '';
        const missingName = await controller.updateName();
        elements.profileName.value = 'Renamed';
        const updated = await controller.updateName();
        const firstDelete = await controller.remove();
        const failedDelete = await controller.remove();
        const selectedAfterFailure = selected;
        const secondConfirm = await controller.remove();
        deleteFails = false;
        const deleted = await controller.remove();
        console.log(JSON.stringify({{
          missing, missingPrompt, saved, saves, missingName, updated, updates, firstDelete, failedDelete, secondConfirm, deleted, deletes,
          selectedAfterFailure, selected, profiles, progress, selections,
        }}));
        """
    )
    assert result["missing"] is False
    assert result["missingPrompt"] is False
    assert result["saved"] == [True, False]
    assert result["saves"] == 1
    assert result["missingName"] is False
    assert result["updated"] is True
    assert result["updates"] == 1
    assert result["firstDelete"] is False
    assert result["failedDelete"] is False
    assert result["selectedAfterFailure"] == "voice_001"
    assert result["secondConfirm"] is False
    assert result["deleted"] is True
    assert result["deletes"] == 2
    assert result["selected"] == ""
    assert result["profiles"] == []
    assert [item[0] for item in result["progress"]] == [
        "profile.save_requirements",
        "profile.save_requirements",
        "profile.saved",
        "profile.name_required",
        "profile.name_updated",
        "profile.confirm_delete",
        "profile.delete_failed",
        "profile.confirm_delete",
        "profile.deleted",
    ]


def test_voice_profile_controller_latest_load_delete_identity_and_temporary_copy_refresh() -> None:
    result = _node(
        f"""
        import {{ createVoiceProfileController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        let selected = '';
        let uploaded = null;
        const listResolvers = [];
        let resolveDelete;
        const selections = [];
        const profileEvents = [];
        const elements = {{
          profileSelect: new FakeElement(), profileId: new FakeElement('draft-id'), profileName: new FakeElement('Draft'),
          promptText: new FakeElement('draft prompt'), recommendedPrompts: new FakeElement(), recommendButton: new FakeElement(),
          saveButton: new FakeElement(), updateButton: new FakeElement(), deleteButton: new FakeElement(),
        }};
        const controller = createVoiceProfileController({{
          elements,
          requests: {{
            list: () => new Promise(resolve => listResolvers.push(resolve)),
            delete: () => new Promise(resolve => {{ resolveDelete = resolve; }}),
          }},
          callbacks: {{
            supportsProfiles: () => true, currentEngineId: () => 'zipvoice', getSelectedVoice: () => selected,
            setSelectedVoice: value => {{ selected = value; }}, getPromptAudioFile: () => uploaded,
            onSelection: value => selections.push(value), onProfilesChanged: value => profileEvents.push([value.selectedVoice, value.changed]),
          }},
          translate: key => `t:${{key}}`,
          environment: {{ document: fakeDocument, setTimeout: () => 1, clearTimeout: () => {{}} }},
        }});
        const first = controller.load();
        const second = controller.load();
        listResolvers[1](new Response(JSON.stringify({{ profiles: [{{ voice_id: 'b', name: 'B', revision: '2' }}] }})));
        await second;
        listResolvers[0](new Response(JSON.stringify({{ profiles: [{{ voice_id: 'a', name: 'A', revision: '1' }}] }})));
        await first;
        const afterLatest = controller.profiles.map(profile => profile.voice_id);
        const refresh = controller.load();
        listResolvers[2](new Response(JSON.stringify({{ profiles: [{{ voice_id: 'a', name: 'A', revision: '1' }}, {{ voice_id: 'b', name: 'B', revision: '2' }}] }})));
        await refresh;
        controller.selectVoice('b');
        await controller.remove();
        const pendingDelete = controller.remove();
        controller.selectVoice('a');
        resolveDelete(new Response(JSON.stringify({{ deleted: true }})));
        const deleted = await pendingDelete;
        const afterDelete = {{ selected, profiles: controller.profiles.map(profile => profile.voice_id), selections }};
        const preserved = {{ id: elements.profileId.value, name: elements.profileName.value, prompt: elements.promptText.value }};
        uploaded = {{ name: 'fresh.wav' }};
        controller.renderCopy();
        const uploadedLabel = elements.profileSelect.children[0].textContent;
        uploaded = null;
        controller.renderCopy();
        const emptyLabel = elements.profileSelect.children[0].textContent;
        console.log(JSON.stringify({{ afterLatest, deleted, afterDelete, profileEvents, preserved, uploadedLabel, emptyLabel }}));
        """
    )
    assert result["afterLatest"] == ["b"]
    assert result["deleted"] is True
    assert result["afterDelete"] == {"selected": "a", "profiles": ["a"], "selections": ["b", "a"]}
    assert result["preserved"] == {"id": "draft-id", "name": "A", "prompt": "draft prompt"}
    assert result["uploadedLabel"] == "t:profile.temporary_clone_uploaded"
    assert result["emptyLabel"] == "t:profile.temporary_clone"


def test_voice_profile_controller_dispose_invalidates_every_pending_operation() -> None:
    result = _node(
        f"""
        import {{ createVoiceProfileController }} from {json.dumps(MODULE.as_uri())};
        {ELEMENT_FIXTURE}
        let selected = 'voice_a';
        const deferred = {{}};
        const wait = name => new Promise(resolve => {{ deferred[name] = resolve; }});
        const elements = {{
          profileSelect: new FakeElement(), profileId: new FakeElement('voice_a'), profileName: new FakeElement('Name'),
          promptText: new FakeElement('prompt'), recommendedPrompts: new FakeElement(), recommendButton: new FakeElement(),
          saveButton: new FakeElement(), updateButton: new FakeElement(), deleteButton: new FakeElement(),
        }};
        const events = [];
        const controller = createVoiceProfileController({{
          elements,
          requests: {{
            list: () => wait('list'), recommended: () => wait('recommended'), save: () => wait('save'), update: () => wait('update'), delete: () => wait('delete'),
          }},
          callbacks: {{
            supportsProfiles: () => true, currentEngineId: () => 'zipvoice', getSelectedVoice: () => selected,
            setSelectedVoice: value => {{ selected = value; }}, getPromptAudioFile: () => ({{ name: 'ref.wav' }}),
            onProfilesChanged: () => events.push('profiles'), onSelection: () => events.push('selection'), onProgress: () => events.push('progress'), onError: () => events.push('error'),
          }},
          environment: {{ document: fakeDocument, setTimeout: () => 1, clearTimeout: () => {{}} }},
        }});
        const load = controller.load();
        controller.dispose();
        deferred.list(new Response(JSON.stringify({{ profiles: [{{ voice_id: 'late' }}] }})));
        const loadResult = await load;
        console.log(JSON.stringify({{ loadResult, selected, profiles: controller.profiles, events, selectChildren: elements.profileSelect.children.length }}));
        """
    )
    assert result == {"loadResult": False, "selected": "voice_a", "profiles": [], "events": [], "selectChildren": 0}


def test_profile_voice_id_placeholder_is_locale_invariant() -> None:
    template = (PACKAGE_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert '<input id="zipvoice-profile-id" placeholder="voice_001"' in template
    assert 'id="zipvoice-profile-id" data-i18n-placeholder' not in template


def test_voice_profile_module_is_native_esm_and_app_only_composes_it() -> None:
    module = MODULE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert re.findall(r"\bexport\s+function\s+(\w+)", module) == ["createVoiceProfileController"]
    assert "import { translate" not in module
    assert "fetch(" not in module
    assert "state." not in module
    assert "createVoiceProfileController" in app
    assert "referenceAudioPreviewController?.previewSaved" in app
    assert "createReferenceRecorderController" in app
    for name in ("saveZipVoiceProfile", "updateSelectedVoiceProfileMetadata", "deleteSelectedVoiceProfile"):
        body = re.search(rf"async function {name}\([^)]*\) \{{(?P<body>.*?)\n\}}", app, re.DOTALL)
        assert body and "voiceProfileController" in body.group("body")
