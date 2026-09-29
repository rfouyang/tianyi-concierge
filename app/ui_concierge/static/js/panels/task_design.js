const EMPTY_DRAFT = () => ({ id: null, name: "", stops: [] });

class TaskDesignPanel {
  constructor(root) {
    this.root = root;
    const q = (selector) => root.querySelector(selector);
    this.el = {
      taskSelect: q("[data-task-select]"),
      refresh: q("[data-task-refresh]"),
      newTask: q("[data-task-new]"),
      dirty: q("[data-task-dirty]"),
      deleteTask: q("[data-task-delete]"),
      save: q("[data-task-save]"),
      name: q("[data-task-name]"),
      stopList: q("[data-stop-list]"),
      stopUp: q("[data-stop-up]"),
      stopDown: q("[data-stop-down]"),
      stopRemove: q("[data-stop-remove]"),
      editorTitle: q("[data-editor-title]"),
      poi: q("[data-editor-poi]"),
      sourceButtons: [...root.querySelectorAll("[data-speech-source]")],
      uploadPanel: q("[data-upload-panel]"),
      uploadInput: q("[data-upload-input]"),
      dropzone: q("[data-dropzone]"),
      uploadFile: q("[data-upload-file]"),
      uploadName: q("[data-upload-name]"),
      uploadMeta: q("[data-upload-meta]"),
      uploadRemove: q("[data-upload-remove]"),
      contentLabel: q("[data-content-label]"),
      content: q("[data-editor-content]"),
      speechState: q("[data-speech-state]"),
      speechRobot: q("[data-speech-robot]"),
      actionList: q("[data-action-list]"),
      timing: q("[data-stop-timing]"),
      actionUp: q("[data-action-up]"),
      actionDown: q("[data-action-down]"),
      actionRemove: q("[data-action-remove]"),
      actionSelect: q("[data-action-select]"),
      actionAdd: q("[data-action-add]"),
      armsConfirm: q("[data-arms-confirm]"),
      rehearse: q("[data-rehearse]"),
      stopAdd: q("[data-stop-add]"),
      stopUpdate: q("[data-stop-update]"),
    };
    this.tasks = [];
    this.pois = [];
    this.actions = [];
    this.draft = EMPTY_DRAFT();
    this.savedJson = JSON.stringify(this.draft);
    this.selectedStop = null;
    this.editor = this.emptyEditor();
    this.selectedAction = null;
    // Prepared speech length in seconds, keyed by speechKey(stop).
    this.speechDurations = new Map();
  }

  emptyEditor() {
    return { poi_id: "", content: "", source: "text", audio: null, audio_name: null, audio_duration: null, actions: [] };
  }

  start() {
    const e = this.el;
    e.taskSelect.addEventListener("change", () => this.loadTask(e.taskSelect.value));
    e.refresh.addEventListener("click", () => this.refresh(this.draft.id));
    e.newTask.addEventListener("click", () => this.newTask());
    const { act } = window.Concierge;
    act(e.deleteTask, () => this.deleteTask());
    act(e.save, () => this.save());
    e.name.addEventListener("input", () => { this.draft.name = e.name.value; this.renderDirty(); this.renderButtons(); });
    e.stopUp.addEventListener("click", () => this.moveStop(-1));
    e.stopDown.addEventListener("click", () => this.moveStop(1));
    e.stopRemove.addEventListener("click", () => this.removeStop());
    e.poi.addEventListener("change", () => { this.editor.poi_id = e.poi.value; });
    e.content.addEventListener("input", () => { this.editor.content = e.content.value; this.renderSpeechState(); });
    for (const button of e.sourceButtons) button.addEventListener("click", () => this.setSource(button.dataset.speechSource));
    e.uploadInput.addEventListener("change", () => this.upload(e.uploadInput.files[0]));
    e.dropzone.addEventListener("dragover", (event) => event.preventDefault());
    e.dropzone.addEventListener("drop", (event) => { event.preventDefault(); this.upload(event.dataTransfer.files[0]); });
    e.uploadRemove.addEventListener("click", () => { Object.assign(this.editor, { audio: null, audio_name: null, audio_duration: null }); this.renderEditor(); });
    act(e.speechRobot, () => this.rehearse({ withActions: false }));
    e.actionList.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-act]");
      if (!button || button.disabled || this.acting) return;
      this.acting = true;
      this.renderButtons();
      button.innerHTML = "Acting…";
      try {
        await this.act(this.editor.actions[Number(button.dataset.act)]);
      } finally {
        this.acting = false;
        this.renderActions();
        this.renderButtons();
      }
    });
    e.actionAdd.addEventListener("click", () => this.addAction());
    e.actionUp.addEventListener("click", () => this.moveAction(-1));
    e.actionDown.addEventListener("click", () => this.moveAction(1));
    e.actionRemove.addEventListener("click", () => this.removeAction());
    e.armsConfirm.addEventListener("change", () => this.renderButtons());
    act(e.rehearse, () => this.rehearse({ withActions: true }));
    e.stopAdd.addEventListener("click", () => this.addStop());
    e.stopUpdate.addEventListener("click", () => this.updateStop());
    document.addEventListener("concierge:busy", () => this.renderButtons());
    window.addEventListener("beforeunload", (event) => { if (this.isDirty()) event.preventDefault(); });
    this.refresh();
  }

  // ------------------------------------------------------------- loading
  async refresh(selectId) {
    const api = window.Concierge.api;
    try {
      const [{ tasks }, catalog] = await Promise.all([api.get("/api/concierge/tasks"), api.get("/api/concierge/tasks/catalog")]);
      this.tasks = tasks;
      this.pois = catalog.pois;
      this.actions = catalog.actions;
      for (const message of catalog.errors ?? []) window.Concierge.toast.show(message, "caution");
      this.renderCatalog();
      const target = tasks.find((task) => task.id === selectId) ?? tasks[0];
      if (target) await this.loadTask(target.id);
      else this.newTask();
    } catch (error) {
      window.Concierge.toast.error(error, "Could not load tasks");
    }
  }

  renderCatalog() {
    const e = this.el;
    e.taskSelect.innerHTML = this.tasks.map((task) => `<option value="${task.id}"></option>`).join("");
    [...e.taskSelect.options].forEach((option, index) => { option.textContent = this.tasks[index].name; });
    e.poi.innerHTML = '<option value="">Choose a POI</option>' + this.pois.map((poi) => `<option value="${poi.id}"></option>`).join("");
    [...e.poi.options].slice(1).forEach((option, index) => {
      const poi = this.pois[index];
      option.textContent = poi.type ? `${poi.name} (${poi.type})` : poi.name;
    });
    e.actionSelect.innerHTML = '<option value="">Tianyi arm action to append</option>' + this.actions.map((action) => `<option value="${action.action_id}">${action.action_id} · ${Math.round(action.duration)} s</option>`).join("");
  }

  async loadTask(taskId) {
    if (this.isDirty() && !window.confirm("Discard unsaved changes to this task?")) {
      this.el.taskSelect.value = this.draft.id ?? "";
      return;
    }
    try {
      const task = await window.Concierge.api.get(`/api/concierge/tasks/${taskId}`);
      this.setDraft(task);
    } catch (error) {
      window.Concierge.toast.error(error, "Could not load the task");
    }
  }

  setDraft(task) {
    this.draft = { id: task.id, name: task.name, stops: structuredClone(task.stops) };
    this.savedJson = JSON.stringify(this.draft);
    const missing = new Set((task.speech?.missing ?? []).map((item) => item.stop_index));
    this.speechDurations = new Map();
    task.stops.forEach((stop, index) => {
      const duration = task.speech?.durations?.[index];
      if (!missing.has(index + 1) && duration != null) this.speechDurations.set(this.speechKey(stop), duration);
    });
    this.el.taskSelect.value = task.id;
    this.selectedStop = null;
    this.editor = this.emptyEditor();
    this.render();
    if (missing.size) {
      window.Concierge.toast.show(
        `Speech is not prepared for ${[...missing].map((i) => task.stops[i - 1].poi_name).join(", ")}. Save the task while online to prepare it.`,
        "caution",
      );
    }
  }

  newTask() {
    if (this.isDirty() && !window.confirm("Discard unsaved changes to this task?")) return;
    this.draft = EMPTY_DRAFT();
    this.savedJson = JSON.stringify(this.draft);
    this.selectedStop = null;
    this.editor = this.emptyEditor();
    this.el.taskSelect.value = "";
    this.render();
  }

  isDirty() {
    return JSON.stringify(this.draft) !== this.savedJson;
  }

  speechKey(stop) {
    return stop.audio ? `upload:${stop.audio}` : `text:${(stop.content ?? "").trim()}`;
  }

  // ------------------------------------------------------------- rendering
  render() {
    this.el.name.value = this.draft.name;
    this.renderStops();
    this.renderEditor();
    this.renderDirty();
  }

  renderDirty() {
    this.el.dirty.hidden = !this.isDirty();
    if (this.el.save) this.renderButtons();
  }

  renderStops() {
    const list = this.el.stopList;
    list.innerHTML = this.draft.stops.map((stop, index) => {
      const selected = index === this.selectedStop;
      const chips = stop.actions.length
        ? stop.actions.map((action) => `<span class="badge badge-neutral">${action.action_id}</span>`).join('<span class="text-ink-3">›</span>')
        : '<span class="text-xs text-ink-3">No actions: arms stay at concierge_init</span>';
      const duration = this.speechDurations.get(this.speechKey(stop));
      const length = duration != null ? `${duration.toFixed(1)} s` : "no speech";
      const speech = `${stop.audio ? '<span class="badge badge-signal">Uploaded WAV</span>' : ""}<span class="badge ${duration != null ? "badge-neutral" : "badge-caution"} ml-auto">${length}</span>`;
      return `<li><button type="button" data-index="${index}" class="flex w-full items-start gap-3 rounded-[10px] border p-3 text-left ${selected ? "border-2 border-signal bg-[#f7fbfa]" : "border-line hover:bg-paper"}">
        <span class="grid size-[26px] shrink-0 place-items-center rounded-full ${selected ? "bg-signal" : "bg-ink"} text-xs font-bold text-white">${index + 1}</span>
        <span class="flex min-w-0 flex-1 flex-col gap-1.5">
          <span class="flex items-center gap-2 text-sm font-semibold"><span data-poi></span>${speech}</span>
          <span class="line-clamp-2 text-[13px] leading-snug text-ink-2" data-content></span>
          <span class="flex flex-wrap items-center gap-1.5">${chips}</span>
        </span></button></li>`;
    }).join("") || '<li class="rounded-[10px] border border-dashed border-line p-6 text-center text-[13px] text-ink-3">No stops yet. Choose a POI on the right and add the first stop.</li>';
    list.querySelectorAll("[data-index]").forEach((button) => {
      const stop = this.draft.stops[Number(button.dataset.index)];
      button.querySelector("[data-poi]").textContent = stop.poi_name;
      button.querySelector("[data-content]").textContent = stop.content;
      button.addEventListener("click", () => this.selectStop(Number(button.dataset.index)));
    });
    const count = this.draft.stops.length;
    const selected = this.selectedStop;
    this.el.stopUp.disabled = selected === null || selected === 0;
    this.el.stopDown.disabled = selected === null || selected >= count - 1;
    this.el.stopRemove.disabled = selected === null;
    this.el.deleteTask.disabled = !this.draft.id;
  }

  renderEditor() {
    const e = this.el;
    const editor = this.editor;
    e.editorTitle.textContent = this.selectedStop === null
      ? "New stop"
      : `Stop ${this.selectedStop + 1}: ${this.draft.stops[this.selectedStop].poi_name}`;
    e.poi.value = editor.poi_id;
    e.content.value = editor.content;
    for (const button of e.sourceButtons) button.setAttribute("aria-selected", String(button.dataset.speechSource === editor.source));
    e.uploadPanel.hidden = editor.source !== "upload";
    e.dropzone.hidden = Boolean(editor.audio);
    e.uploadFile.hidden = !editor.audio;
    e.uploadName.textContent = editor.audio_name || editor.audio || "";
    e.uploadMeta.textContent = editor.audio_duration ? `${editor.audio_duration} s · 16 kHz mono 16-bit` : "16 kHz mono 16-bit";
    e.contentLabel.textContent = editor.source === "upload" ? "Transcript" : "Text to speak on arrival";
    this.renderActions();
    this.renderSpeechState();
    this.renderButtons();
  }

  renderActions() {
    this.renderTiming();
    const list = this.el.actionList;
    const byId = Object.fromEntries(this.actions.map((action) => [action.action_id, action]));
    list.innerHTML = this.editor.actions.map((action, index) => {
      const selected = index === this.selectedAction;
      const duration = byId[action.action_id]?.duration;
      return `<li class="flex items-center gap-2.5 rounded-lg border px-3 py-2 ${selected ? "border-signal bg-signal-soft" : "border-line"}">
        <button type="button" class="flex flex-1 items-center gap-2.5 text-left" data-select="${index}">
          <span class="text-xs font-bold text-ink-3">${index + 1}</span><span class="text-[13px] font-medium">${action.action_id}</span>
          <span class="ml-auto text-xs text-ink-3">${duration ? `${Math.round(duration)} s` : ""}</span></button>
        <button type="button" class="btn btn-secondary btn-sm" data-act="${index}"><svg class="size-3" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4v16l13-8z"/></svg>Act</button>
      </li>`;
    }).join("") || '<li class="text-xs text-ink-3">No actions: the arms stay at concierge_init while Tianyi speaks.</li>';
    list.querySelectorAll("[data-select]").forEach((button) => button.addEventListener("click", () => {
      const index = Number(button.dataset.select);
      this.selectedAction = this.selectedAction === index ? null : index;
      this.renderActions();
      this.renderButtons();
    }));

  }

  renderSpeechState() {
    const badge = this.el.speechState;
    const duration = this.editorSpeechDuration();
    const prepared = Boolean(this.editor.audio) || duration != null;
    const length = duration != null ? ` · ${duration.toFixed(1)} s` : "";
    badge.textContent = this.editor.source === "upload"
      ? (this.editor.audio ? `Uploaded WAV${length}` : "No WAV uploaded")
      : prepared ? `Speech prepared${length}` : "Not prepared yet";
    badge.className = `badge ${prepared ? "badge-ok badge-dot" : "badge-neutral"}`;
    this.renderTiming();
  }

  editorSpeechDuration() {
    if (this.editor.audio && this.editor.audio_duration != null) return this.editor.audio_duration;
    return this.speechDurations.get(this.speechKey(this.editor)) ?? null;
  }

  actionsDuration(actions) {
    const byId = Object.fromEntries(this.actions.map((action) => [action.action_id, action]));
    return actions.reduce((total, action) => total + (byId[action.action_id]?.duration ?? 0), 0);
  }

  /** Speech and action lengths side by side; the stop ends when both are done. */
  renderTiming() {
    const node = this.el.timing;
    if (!node) return;
    const speech = this.editorSpeechDuration();
    const actions = this.actionsDuration(this.editor.actions);
    const parts = [
      `Speech ${speech != null ? `${speech.toFixed(1)} s` : "not prepared"}`,
      `Actions ${actions ? `${actions.toFixed(1)} s` : "none"}`,
    ];
    const stopLength = Math.max(speech ?? 0, actions);
    let note = stopLength ? ` · Stop takes about ${stopLength.toFixed(1)} s` : "";
    let caution = false;
    if (speech != null && actions > speech + 0.5) {
      note = ` · Actions run ${(actions - speech).toFixed(1)} s longer than the speech; the stop waits for them`;
      caution = true;
    }
    node.textContent = parts.join(" · ") + note;
    node.className = `text-xs leading-snug ${caution ? "text-caution font-semibold" : "text-ink-3"}`;
  }

  renderButtons() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    const e = this.el;
    const busy = [c.busy[0] || this.acting, c.busy[1]];
    const selectedAction = this.selectedAction;
    const count = this.editor.actions.length;
    const noSpeech = [!this.hasSpeech(), this.editor.source === "upload" ? "Upload a WAV first" : "Enter the text to speak"];
    const unconfirmed = [!e.armsConfirm.checked, "Confirm the arm areas are clear first"];
    e.actionUp.disabled = selectedAction === null || selectedAction === 0;
    e.actionDown.disabled = selectedAction === null || selectedAction >= count - 1;
    e.actionRemove.disabled = selectedAction === null;
    e.stopUpdate.disabled = this.selectedStop === null;
    gate(e.speechRobot, blocked(busy, c.offline, c.moving, noSpeech));
    gate(e.rehearse, blocked(
      busy, c.offline, c.moving, c.mapping,
      [!count && !this.hasSpeech(), "Add an action or some speech to rehearse"],
      count ? c.armsNotReady : [false, ""],
      count ? unconfirmed : [false, ""],
    ));
    for (const button of e.actionList.querySelectorAll("[data-act]")) {
      gate(button, blocked(busy, c.offline, c.moving, c.mapping, c.armsNotReady, unconfirmed));
    }
    gate(e.save, blocked(
      [!this.draft.name.trim(), "Enter a task name"],
      [!this.draft.stops.length, "Add at least one stop"],
      [!this.isDirty(), "No unsaved changes"],
    ));
  }

  hasSpeech() {
    return this.editor.source === "upload" ? Boolean(this.editor.audio) : Boolean(this.editor.content.trim());
  }

  // ------------------------------------------------------------- editing
  setSource(source) {
    this.editor.source = source;
    if (source === "text") Object.assign(this.editor, { audio: null, audio_name: null, audio_duration: null });
    this.renderEditor();
  }

  selectStop(index) {
    if (this.selectedStop === index) {
      this.selectedStop = null;
      this.editor = this.emptyEditor();
    } else {
      const stop = this.draft.stops[index];
      this.selectedStop = index;
      this.editor = {
        poi_id: stop.poi_id,
        content: stop.content,
        source: stop.audio ? "upload" : "text",
        audio: stop.audio ?? null,
        audio_name: stop.audio_name ?? null,
        audio_duration: null,
        actions: structuredClone(stop.actions),
      };
    }
    this.selectedAction = null;
    this.renderStops();
    this.renderEditor();
  }

  editorStop() {
    const poi = this.pois.find((item) => item.id === this.editor.poi_id);
    if (!poi) throw new Error("Choose a POI on the current map first");
    const content = this.editor.content.trim();
    if (!content) throw new Error(this.editor.source === "upload" ? "Enter a transcript for the uploaded speech" : "Enter what Tianyi should say at this POI");
    if (this.editor.source === "upload" && !this.editor.audio) throw new Error("Upload a WAV or switch to Generate from text");
    const stop = { poi_id: poi.id, poi_name: poi.name, content, actions: structuredClone(this.editor.actions) };
    if (this.editor.audio) Object.assign(stop, { audio: this.editor.audio, audio_name: this.editor.audio_name });
    return stop;
  }

  addStop() {
    try {
      this.draft.stops.push(this.editorStop());
      this.selectedStop = null;
      this.editor = this.emptyEditor();
      this.render();
    } catch (error) {
      window.Concierge.toast.error(error);
    }
  }

  updateStop() {
    try {
      this.draft.stops[this.selectedStop] = this.editorStop();
      this.render();
    } catch (error) {
      window.Concierge.toast.error(error);
    }
  }

  moveStop(direction) {
    const from = this.selectedStop;
    const to = from + direction;
    const stops = this.draft.stops;
    if (from === null || to < 0 || to >= stops.length) return;
    [stops[from], stops[to]] = [stops[to], stops[from]];
    this.selectedStop = to;
    this.render();
  }

  removeStop() {
    if (this.selectedStop === null) return;
    this.draft.stops.splice(this.selectedStop, 1);
    this.selectedStop = null;
    this.editor = this.emptyEditor();
    this.render();
  }

  addAction() {
    const actionId = this.el.actionSelect.value;
    if (!actionId) return;
    this.editor.actions.push({ action_id: actionId, phase: "with_speech", required: true });
    this.selectedAction = this.editor.actions.length - 1;
    this.el.actionSelect.value = "";
    this.renderActions();
    this.renderButtons();
  }

  moveAction(direction) {
    const from = this.selectedAction;
    const to = from + direction;
    const actions = this.editor.actions;
    if (from === null || to < 0 || to >= actions.length) return;
    [actions[from], actions[to]] = [actions[to], actions[from]];
    this.selectedAction = to;
    this.renderActions();
    this.renderButtons();
  }

  removeAction() {
    if (this.selectedAction === null) return;
    this.editor.actions.splice(this.selectedAction, 1);
    this.selectedAction = null;
    this.renderActions();
    this.renderButtons();
  }

  // ------------------------------------------------------ speech & robot
  async upload(file) {
    if (!file) return;
    try {
      const stored = await window.Concierge.api.request("POST", "/api/concierge/tasks/speech/upload", file, {
        raw: true,
        headers: { "Content-Type": "audio/wav" },
      });
      Object.assign(this.editor, { audio: stored.file, audio_name: file.name, audio_duration: stored.duration });
      this.renderEditor();
      window.Concierge.toast.show(`${file.name} is a valid 16 kHz mono WAV (${stored.duration} s).`, "ok");
    } catch (error) {
      window.Concierge.toast.error(error, "WAV rejected");
    } finally {
      this.el.uploadInput.value = "";
    }
  }

  /** Prepare generated speech (design stage) so Tianyi can play it; records its length. */
  async prepareSpeech() {
    if (this.editor.audio || !this.editor.content.trim()) return;
    if (this.speechDurations.has(this.speechKey(this.editor))) return;
    this.el.speechState.textContent = "Preparing speech…";
    const prepared = await window.Concierge.api.post("/api/concierge/tasks/speech/preview", {
      text: this.editor.content.trim(),
    });
    if (prepared.duration != null) this.speechDurations.set(this.speechKey(this.editor), prepared.duration);
    this.renderSpeechState();
  }

  async rehearse({ withActions }) {
    const body = {
      actions: withActions ? this.editor.actions : [],
      content: this.editor.content.trim() || null,
      audio: this.editor.audio,
      arms_confirmed: this.el.armsConfirm.checked,
    };
    try {
      await this.prepareSpeech();
      await window.Concierge.runOperation("/api/concierge/tasks/rehearse", body, {
        success: withActions ? "Rehearsal finished. The arms are back at concierge_init." : "Tianyi played the speech.",
      });
      this.renderSpeechState();
    } catch {
      /* reported */
    }
  }

  async act(action) {
    try {
      await window.Concierge.runOperation(
        "/api/concierge/tasks/rehearse",
        { actions: [action], content: null, audio: null, arms_confirmed: this.el.armsConfirm.checked },
        { success: `${action.action_id} finished. The arms are back at concierge_init.` },
      );
    } catch {
      /* reported */
    }
  }

  // --------------------------------------------------------------- saving
  async save() {
    const api = window.Concierge.api;
    const body = { name: this.draft.name.trim(), stops: this.draft.stops };
    try {
      if (!body.name) throw new Error("Enter a task name");
      if (!body.stops.length) throw new Error("Add at least one stop");
      const task = this.draft.id
        ? await api.put(`/api/concierge/tasks/${this.draft.id}`, body)
        : await api.post("/api/concierge/tasks", body);
      const speech = task.speech ?? {};
      if (speech.ready) window.Concierge.toast.show(`Saved ${task.name}. Speech is prepared for every stop.`, "ok");
      else window.Concierge.toast.show(`Saved ${task.name}, but speech is missing for ${speech.missing.map((m) => m.poi_name).join(", ")}. Connect to the network and save again.`, "caution", { timeout: 10000 });
      const { tasks } = await api.get("/api/concierge/tasks");
      this.tasks = tasks;
      this.renderCatalog();
      this.savedJson = JSON.stringify(this.draft);
      await this.loadTask(task.id);
    } catch (error) {
      window.Concierge.toast.error(error, "Save task failed");
    }
  }

  async deleteTask() {
    if (!this.draft.id || !window.confirm(`Delete task ${this.draft.name}? This cannot be undone.`)) return;
    try {
      await window.Concierge.api.delete(`/api/concierge/tasks/${this.draft.id}`);
      window.Concierge.toast.show(`Deleted task ${this.draft.name}.`, "ok");
      this.savedJson = JSON.stringify(this.draft);
      this.refresh();
    } catch (error) {
      window.Concierge.toast.error(error, "Delete task failed");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="task-design"]');
  if (root) new TaskDesignPanel(root).start();
});
