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
  let lifecycleGeneration = 0;
  let listGeneration = 0;
  let recommendedGeneration = 0;
  let saveGeneration = 0;
  let updateGeneration = 0;
  let deleteGeneration = 0;

  function isActive(lifecycle) {
    return !disposed && lifecycle === lifecycleGeneration;
  }

  function isCurrent(lifecycle, generation, currentGeneration, engineId) {
    if (!isActive(lifecycle) || generation !== currentGeneration()) return false;
    if (currentEngineId() !== engineId) return false;
    return true;
  }

  function findProfile(voiceId) {
    return profiles.find(profile => profile.voice_id === voiceId) || null;
  }

  function upsertProfile(profile) {
    const voiceId = String(profile?.voice_id || '').trim();
    if (!voiceId) return false;
    const nextProfile = { ...profile, voice_id: voiceId };
    const index = profiles.findIndex(item => item.voice_id === voiceId);
    if (index < 0) profiles = [...profiles, nextProfile];
    else profiles = profiles.map((item, itemIndex) => itemIndex === index ? nextProfile : item);
    profilesLoaded = true;
    signature = profileSignature(profiles);
    return true;
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
    if (disposed) return;
    const selectedVoice = getSelectedVoice();
    if (elements.updateButton) elements.updateButton.disabled = !selectedVoice || updateInFlight;
    if (!elements.deleteButton) return;
    const confirming = Boolean(deleteConfirmation) && deleteConfirmation === selectedVoice;
    elements.deleteButton.disabled = !selectedVoice || deleteInFlight;
    elements.deleteButton.dataset.confirming = confirming ? selectedVoice : '';
    const deleteLabel = confirming
      ? translate('profile.confirm_delete_button')
      : translate('profile.delete');
    elements.deleteButton.textContent = deleteLabel;
    elements.deleteButton.classList?.toggle?.('confirming', confirming);
  }

  function renderProfileSelect() {
    if (disposed || !elements.profileSelect) return;
    elements.profileSelect.innerHTML = '';
    const temporary = makeOption('', temporaryLabel());
    if (temporary) elements.profileSelect.appendChild(temporary);
    profiles.forEach(profile => {
      const option = makeOption(profile.voice_id, profile.name || profile.voice_id);
      if (option) elements.profileSelect.appendChild(option);
    });
    elements.profileSelect.value = findProfile(getSelectedVoice()) ? getSelectedVoice() : '';
  }

  function renderCopy() {
    if (disposed) return;
    renderProfileSelect();
    setButtonState();
  }

  function clearDeleteConfirmation({ render = true } = {}) {
    if (deleteConfirmationTimer !== null) {
      env.cancelTimer?.(deleteConfirmationTimer);
      deleteConfirmationTimer = null;
    }
    deleteConfirmation = '';
    if (render) setButtonState();
  }

  function resetDeleteConfirmation() {
    clearDeleteConfirmation();
  }

  function selectVoice(voiceId, { notify = true } = {}) {
    if (disposed) return getSelectedVoice();
    const nextVoiceId = findProfile(voiceId) ? voiceId : '';
    const changed = nextVoiceId !== getSelectedVoice();
    setSelectedVoice(nextVoiceId);
    if (elements.profileSelect) elements.profileSelect.value = nextVoiceId;
    if (elements.profileName) elements.profileName.value = findProfile(nextVoiceId)?.name || '';
    clearDeleteConfirmation();
    if (notify && changed) onSelection(nextVoiceId, { changed });
    return nextVoiceId;
  }

  async function responseError(response, isOperationCurrent) {
    try {
      const message = String(await readError(response) || '').trim();
      return isOperationCurrent() ? message : '';
    } catch (_) {
      return '';
    }
  }

  async function load({ forcePreview = false } = {}) {
    if (disposed || !supportsProfiles() || typeof requestList !== 'function') return false;
    const lifecycle = lifecycleGeneration;
    const generation = ++listGeneration;
    const engineId = currentEngineId();
    const current = () => isCurrent(lifecycle, generation, () => listGeneration, engineId);
    try {
      const response = await requestList({ engineId });
      if (!current() || !response?.ok) return false;
      const data = await response.json();
      if (!current() || !supportsProfiles()) return false;
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
    const lifecycle = lifecycleGeneration;
    const generation = ++recommendedGeneration;
    const engineId = currentEngineId();
    const current = () => isCurrent(lifecycle, generation, () => recommendedGeneration, engineId);
    try {
      const response = await requestRecommended({ engineId });
      if (!current() || !response?.ok) return false;
      const data = await response.json();
      if (!current()) return false;
      (data.items || []).forEach(prompt => {
        const button = env.document?.createElement?.('button');
        if (!button) return;
        button.type = 'button';
        button.className = 'prompt-chip';
        button.textContent = prompt;
        button.addEventListener('click', () => {
          if (!disposed && elements.promptText) elements.promptText.value = prompt;
        });
        container.appendChild(button);
      });
      container.hidden = false;
      return true;
    } catch (_) {
      return false;
    }
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
    const lifecycle = lifecycleGeneration;
    const generation = ++saveGeneration;
    const engineId = currentEngineId();
    const current = () => isCurrent(lifecycle, generation, () => saveGeneration, engineId);
    saveInFlight = true;
    if (elements.saveButton) elements.saveButton.disabled = true;
    try {
      const response = await requestSave({ file, promptText, voiceId, name, engineId });
      if (!current()) return false;
      if (!response?.ok) throw new Error(await responseError(response, current));
      if (!current()) return false;
      const data = await response.json();
      if (!current()) return false;
      const savedProfile = data.profile;
      const savedVoiceId = String(savedProfile?.voice_id || '').trim();
      if (!savedVoiceId || !upsertProfile(savedProfile)) throw new Error('');
      setSelectedVoice(savedVoiceId);
      renderCopy();
      selectVoice(savedVoiceId, { notify: false });
      onProfilesChanged({
        profiles: profiles.map(profile => ({ ...profile })),
        selectedVoice: savedVoiceId,
        changed: true,
        forcePreview: true,
      });
      onProgress(descriptor('profile.saved', { name: data.profile?.name || savedVoiceId }));
      await load({ forcePreview: true });
      return isActive(lifecycle) && generation === saveGeneration;
    } catch (error) {
      if (current()) onError(error, descriptor('profile.save_failed'));
      return false;
    } finally {
      if (generation === saveGeneration) {
        saveInFlight = false;
        if (!disposed && elements.saveButton) elements.saveButton.disabled = false;
      }
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
    const lifecycle = lifecycleGeneration;
    const generation = ++updateGeneration;
    const engineId = currentEngineId();
    const current = () => isCurrent(lifecycle, generation, () => updateGeneration, engineId);
    updateInFlight = true;
    setButtonState();
    try {
      const response = await requestUpdate({ engineId, voiceId, name });
      if (!current()) return false;
      if (!response?.ok) throw new Error(await responseError(response, current));
      if (!current()) return false;
      await load({ forcePreview: false });
      if (!current()) return false;
      onProgress(descriptor('profile.name_updated'));
      return true;
    } catch (error) {
      if (current()) onError(error, descriptor('profile.update_failed'));
      return false;
    } finally {
      if (generation === updateGeneration) {
        updateInFlight = false;
        if (!disposed) setButtonState();
        if (current()) clearDeleteConfirmation();
      }
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
        if (!disposed && deleteConfirmation === voiceId) clearDeleteConfirmation();
      }, 6000) ?? null;
      setButtonState();
      onProgress(descriptor('profile.confirm_delete', { name }), true);
      return false;
    }
    const lifecycle = lifecycleGeneration;
    const generation = ++deleteGeneration;
    const engineId = currentEngineId();
    const current = () => isCurrent(lifecycle, generation, () => deleteGeneration, engineId);
    deleteInFlight = true;
    setButtonState();
    try {
      const response = await requestDelete({ engineId, voiceId, operation: generation });
      if (!current()) return false;
      if (!response?.ok) throw new Error(await responseError(response, current));
      if (!current()) return false;
      const result = await response.json();
      if (!current()) return false;
      if (!result.deleted) {
        onError(new Error(''), descriptor('profile.delete_missing'));
        return false;
      }
      const deletedSelectedVoice = getSelectedVoice() === voiceId;
      if (deletedSelectedVoice) setSelectedVoice('');
      profiles = profiles.filter(profile => profile.voice_id !== voiceId);
      signature = profileSignature(profiles);
      renderCopy();
      const selectedVoice = getSelectedVoice();
      onProfilesChanged({
        profiles: profiles.map(profile => ({ ...profile })),
        selectedVoice,
        changed: true,
        forcePreview: false,
      });
      if (deletedSelectedVoice) onSelection('', { changed: true, deleted: true });
      onProgress(descriptor('profile.deleted', { name }));
      return true;
    } catch (error) {
      if (current()) onError(error, descriptor('profile.delete_failed'));
      return false;
    } finally {
      if (generation === deleteGeneration) {
        deleteInFlight = false;
        if (!disposed) setButtonState();
        if (current()) clearDeleteConfirmation();
      }
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
    lifecycleGeneration += 1;
    clearDeleteConfirmation({ render: false });
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
