function descriptor(key, params = null) {
  return { key, params };
}

function profileSignature(profiles) {
  return JSON.stringify(profiles.map(profile => [profile.voice_id, profile.name || '', profile.revision || '']));
}

export function createVoiceProfileController({
  elements = {},
  requests = {},
  callbacks = {},
  translate = key => key,
  environment = {},
} = {}) {
  const env = {
    document: environment.document ?? globalThis.document,
    schedule: environment.setTimeout ?? ((callback, delay) => globalThis.setTimeout(callback, delay)),
    cancelTimer: environment.clearTimeout ?? (timer => globalThis.clearTimeout(timer)),
  };
  const supportsProfiles = callbacks.supportsProfiles ?? (() => false);
  const currentEngineId = callbacks.currentEngineId ?? (() => '');
  const getSelectedVoice = callbacks.getSelectedVoice ?? (() => '');
  const setSelectedVoice = callbacks.setSelectedVoice ?? (() => {});
  const getPromptAudioFile = callbacks.getPromptAudioFile ?? (() => null);
  const ensureSaveAuthorized = callbacks.ensureSaveAuthorized ?? (() => true);
  const ensureDeleteAuthorized = callbacks.ensureDeleteAuthorized ?? (() => true);
  const onProfilesChanged = callbacks.onProfilesChanged ?? (() => {});
  const onSelection = callbacks.onSelection ?? (() => {});
  const onProgress = callbacks.onProgress ?? (() => {});
  const onError = callbacks.onError ?? (() => {});
  const requestList = requests.list;
  const requestSave = requests.save;
  const requestUpdate = requests.update;
  const requestDelete = requests.delete;
  const requestRecommended = requests.recommended;
  const readError = requests.readError ?? (async response => response.statusText || '');

  let profiles = [];
  let profilesLoaded = false;
  let signature = '';
  let deleteConfirmation = '';
  let deleteConfirmationTimer = null;
  let saveInFlight = false;
  let updateInFlight = false;
  let deleteInFlight = false;
  let disposed = false;

  function findProfile(voiceId) {
    return profiles.find(profile => profile.voice_id === voiceId) || null;
  }

  function displayName(voiceId) {
    return findProfile(voiceId)?.name || voiceId;
  }

  function makeOption(value, text) {
    const option = env.document?.createElement?.('option');
    if (!option) return null;
    option.value = value;
    option.textContent = text;
    return option;
  }

  function temporaryLabel() {
    return translate(getPromptAudioFile() ? 'profile.temporary_clone_uploaded' : 'profile.temporary_clone');
  }

  function setButtonState() {
    const selectedVoice = getSelectedVoice();
    if (elements.updateButton) elements.updateButton.disabled = !selectedVoice || updateInFlight;
    if (!elements.deleteButton) return;
    const confirming = Boolean(deleteConfirmation) && deleteConfirmation === selectedVoice;
    elements.deleteButton.disabled = !selectedVoice || deleteInFlight;
    elements.deleteButton.dataset.confirming = confirming ? selectedVoice : '';
    const deleteLabel = translate(confirming ? 'profile.confirm_delete_button' : 'profile.delete');
    elements.deleteButton.textContent = deleteLabel;
    elements.deleteButton.classList?.toggle?.('confirming', confirming);
  }

  function renderProfileSelect() {
    const select = elements.profileSelect;
    if (!select) return;
    select.innerHTML = '';
    const temporary = makeOption('', temporaryLabel());
    if (temporary) select.appendChild(temporary);
    profiles.forEach(profile => {
      const option = makeOption(profile.voice_id, profile.name || profile.voice_id);
      if (option) select.appendChild(option);
    });
    select.value = findProfile(getSelectedVoice()) ? getSelectedVoice() : '';
  }

  function renderCopy() {
    if (disposed) return;
    renderProfileSelect();
    setButtonState();
  }

  function clearDeleteConfirmation() {
    if (deleteConfirmationTimer !== null) {
      env.cancelTimer?.(deleteConfirmationTimer);
      deleteConfirmationTimer = null;
    }
    deleteConfirmation = '';
    setButtonState();
  }

  function resetDeleteConfirmation() {
    clearDeleteConfirmation();
  }

  function selectVoice(voiceId, { notify = true } = {}) {
    const nextVoiceId = findProfile(voiceId) ? voiceId : '';
    const changed = nextVoiceId !== getSelectedVoice();
    setSelectedVoice(nextVoiceId);
    if (elements.profileSelect) elements.profileSelect.value = nextVoiceId;
    if (elements.profileName) elements.profileName.value = findProfile(nextVoiceId)?.name || '';
    clearDeleteConfirmation();
    if (notify && (changed || nextVoiceId)) onSelection(nextVoiceId, { changed });
    return nextVoiceId;
  }

  async function responseError(response) {
    try {
      return String(await readError(response) || '').trim();
    } catch (_) {
      return '';
    }
  }

  async function load({ forcePreview = false } = {}) {
    if (disposed || !supportsProfiles() || typeof requestList !== 'function') return false;
    const engineId = currentEngineId();
    try {
      const response = await requestList({ engineId });
      if (!response?.ok) return false;
      const data = await response.json();
      if (disposed || !supportsProfiles() || currentEngineId() !== engineId) return false;
      const nextProfiles = Array.isArray(data.profiles) ? data.profiles : [];
      const nextSignature = profileSignature(nextProfiles);
      const changed = !profilesLoaded || nextSignature !== signature;
      profiles = nextProfiles;
      profilesLoaded = true;
      signature = nextSignature;
      const selectedBefore = getSelectedVoice();
      const selectedVoice = findProfile(selectedBefore) ? selectedBefore : '';
      if (selectedVoice !== selectedBefore) setSelectedVoice('');
      if (changed || selectedVoice !== selectedBefore) renderCopy();
      if (changed || selectedVoice !== selectedBefore || forcePreview) {
        onProfilesChanged({
          profiles: profiles.map(profile => ({ ...profile })),
          selectedVoice,
          changed,
          forcePreview,
        });
      }
      return true;
    } catch (_) {
      // Existing app behavior treats profile-list availability as non-blocking.
      return false;
    }
  }

  async function loadRecommendedPrompts() {
    const container = elements.recommendedPrompts;
    if (disposed || !container || typeof requestRecommended !== 'function') return false;
    if (container.childElementCount) {
      container.hidden = !container.hidden;
      return true;
    }
    const response = await requestRecommended({ engineId: currentEngineId() });
    if (!response?.ok) return false;
    const data = await response.json();
    (data.items || []).forEach(prompt => {
      const button = env.document?.createElement?.('button');
      if (!button) return;
      button.type = 'button';
      button.className = 'prompt-chip';
      button.textContent = prompt;
      button.addEventListener('click', () => {
        if (elements.promptText) elements.promptText.value = prompt;
      });
      container.appendChild(button);
    });
    container.hidden = false;
    return true;
  }

  async function save() {
    if (disposed || saveInFlight || !supportsProfiles() || typeof requestSave !== 'function') return false;
    if (!ensureSaveAuthorized()) return false;
    const file = getPromptAudioFile();
    const promptText = String(elements.promptText?.value || '').trim();
    const voiceId = String(elements.profileId?.value || '').trim();
    const name = String(elements.profileName?.value || '').trim();
    if (!file || !promptText || !voiceId) {
      onProgress(descriptor('profile.save_requirements'), true);
      return false;
    }
    saveInFlight = true;
    if (elements.saveButton) elements.saveButton.disabled = true;
    try {
      const response = await requestSave({ file, promptText, voiceId, name, engineId: currentEngineId() });
      if (!response?.ok) throw new Error(await responseError(response));
      const data = await response.json();
      const savedVoiceId = data.profile?.voice_id;
      if (!savedVoiceId) throw new Error('');
      setSelectedVoice(savedVoiceId);
      await load({ forcePreview: true });
      selectVoice(savedVoiceId, { notify: false });
      onProgress(descriptor('profile.saved', { name: data.profile?.name || savedVoiceId }));
      return true;
    } catch (error) {
      onError(error, descriptor('profile.save_failed'));
      return false;
    } finally {
      saveInFlight = false;
      if (elements.saveButton) elements.saveButton.disabled = false;
      clearDeleteConfirmation();
    }
  }

  async function updateName() {
    if (disposed || updateInFlight || !supportsProfiles() || typeof requestUpdate !== 'function') return false;
    const voiceId = getSelectedVoice();
    if (!voiceId) {
      onProgress(descriptor('profile.select_saved_first'), true);
      return false;
    }
    const name = String(elements.profileName?.value || '').trim();
    if (!name) {
      onProgress(descriptor('profile.name_required'), true);
      return false;
    }
    updateInFlight = true;
    setButtonState();
    try {
      const response = await requestUpdate({ engineId: currentEngineId(), voiceId, name });
      if (!response?.ok) throw new Error(await responseError(response));
      await load({ forcePreview: false });
      onProgress(descriptor('profile.name_updated'));
      return true;
    } catch (error) {
      onError(error, descriptor('profile.update_failed'));
      return false;
    } finally {
      updateInFlight = false;
      clearDeleteConfirmation();
    }
  }

  async function remove() {
    if (disposed || deleteInFlight || !supportsProfiles() || typeof requestDelete !== 'function') return false;
    if (!ensureDeleteAuthorized()) return false;
    const voiceId = getSelectedVoice();
    if (!voiceId) {
      onProgress(descriptor('profile.select_saved_first'), true);
      return false;
    }
    const name = displayName(voiceId);
    if (deleteConfirmation !== voiceId) {
      deleteConfirmation = voiceId;
      if (deleteConfirmationTimer !== null) env.cancelTimer?.(deleteConfirmationTimer);
      deleteConfirmationTimer = env.schedule?.(() => {
        if (deleteConfirmation === voiceId) clearDeleteConfirmation();
      }, 6000) ?? null;
      setButtonState();
      onProgress(descriptor('profile.confirm_delete', { name }), true);
      return false;
    }
    deleteInFlight = true;
    setButtonState();
    try {
      const response = await requestDelete({ engineId: currentEngineId(), voiceId });
      if (!response?.ok) throw new Error(await responseError(response));
      const result = await response.json();
      if (!result.deleted) throw new Error('');
      setSelectedVoice('');
      clearDeleteConfirmation();
      await load();
      onSelection('', { changed: true, deleted: true });
      onProgress(descriptor('profile.deleted', { name }));
      return true;
    } catch (error) {
      onError(error, descriptor('profile.delete_failed'));
      return false;
    } finally {
      deleteInFlight = false;
      clearDeleteConfirmation();
    }
  }

  const handlers = {
    select: () => selectVoice(elements.profileSelect?.value || ''),
    recommend: () => { void loadRecommendedPrompts(); },
    save: () => { void save(); },
    update: () => { void updateName(); },
    remove: () => { void remove(); },
  };
  elements.profileSelect?.addEventListener?.('change', handlers.select);
  elements.recommendButton?.addEventListener?.('click', handlers.recommend);
  elements.saveButton?.addEventListener?.('click', handlers.save);
  elements.updateButton?.addEventListener?.('click', handlers.update);
  elements.deleteButton?.addEventListener?.('click', handlers.remove);

  function dispose() {
    if (disposed) return;
    disposed = true;
    clearDeleteConfirmation();
    elements.profileSelect?.removeEventListener?.('change', handlers.select);
    elements.recommendButton?.removeEventListener?.('click', handlers.recommend);
    elements.saveButton?.removeEventListener?.('click', handlers.save);
    elements.updateButton?.removeEventListener?.('click', handlers.update);
    elements.deleteButton?.removeEventListener?.('click', handlers.remove);
  }

  return Object.freeze({
    load,
    loadRecommendedPrompts,
    save,
    updateName,
    remove,
    selectVoice,
    resetDeleteConfirmation,
    renderCopy,
    dispose,
    findProfile,
    displayName,
    get profiles() { return profiles.map(profile => ({ ...profile })); },
    get profilesLoaded() { return profilesLoaded; },
    get signature() { return signature; },
    get deleteConfirmation() { return deleteConfirmation; },
  });
}
