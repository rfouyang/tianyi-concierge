const STATUS_TONES = {
  Completed: "badge-ok",
  Failed: "badge-stop",
  Cancelled: "badge-neutral",
  Pending: "badge-neutral",
};

class TaskExecutionPanel {
  constructor(root) {
    this.root = root;
    const q = (selector) => root.querySelector(selector);
    this.map = new window.Concierge.MapView(q("[data-map-view]"));
    this.taskSelect = q("[data-exec-task]");
    this.speechWarning = q("[data-exec-speech]");
    this.confirm = q("[data-exec-confirm]");
    this.runButton = q("[data-exec-run]");
    this.cancelButton = q("[data-exec-cancel]");
    this.resumeButton = q("[data-exec-resume]");
    this.summary = q("[data-exec-summary]");
    this.state = q("[data-exec-state]");
    this.rows = q("[data-exec-rows]");
    this.eventMeta = q("[data-exec-event-meta]");
    this.eventText = q("[data-exec-event]");
    this.badge = document.getElementById("exec-badge");
    window.Concierge.bindLocalizationHint(root.querySelector("[data-localization-hint]"));
    this.tasks = [];
    this.task = null;
    this.checkpoint = null;
    this.speechReady = false;
  }

  start() {
    this.taskSelect.addEventListener("change", () => this.selectTask(this.taskSelect.value));
    this.confirm.addEventListener("change", () => this.renderButtons());
    const { act } = window.Concierge;
    act(this.runButton, () => this.run(false));
    act(this.resumeButton, () => this.run(true));
    act(this.cancelButton, () => this.cancel());
    document.addEventListener("concierge:busy", () => this.renderButtons());
    document.addEventListener("concierge:status", (event) => this.renderStatus(event.detail));
    document.addEventListener("concierge:operations", (event) => this.renderOperation(event.detail.current, event.detail.previous));
    this.map.load();
    this.loadTasks();
  }

  async loadTasks() {
    try {
      const { tasks } = await window.Concierge.api.get("/api/concierge/tasks");
      this.tasks = tasks;
      this.taskSelect.innerHTML = tasks.map((task) => `<option value="${task.id}"></option>`).join("");
      [...this.taskSelect.options].forEach((option, index) => { option.textContent = tasks[index].name; });
      const running = window.Concierge.state.operations?.active;
      const selected = running?.kind === "task" ? running.details.task_id : tasks[0]?.id;
      if (selected) {
        this.taskSelect.value = selected;
        await this.selectTask(selected);
      }
    } catch (error) {
      window.Concierge.toast.error(error, "Could not load tasks");
    }
  }

  async selectTask(taskId) {
    try {
      const [task, execution] = await Promise.all([
        window.Concierge.api.get(`/api/concierge/tasks/${taskId}`),
        window.Concierge.api.get("/api/concierge/execution"),
      ]);
      this.task = task;
      this.checkpoint = execution.checkpoint?.task_id === taskId ? execution.checkpoint : null;
      this.speechReady = Boolean(task.speech?.ready);
      this.speechWarning.hidden = this.speechReady;
      this.speechWarning.textContent = this.speechReady
        ? ""
        : `Speech is not prepared for ${task.speech.missing.map((m) => m.poi_name).join(", ")}. Save the task in Task design while online.`;
      this.renderOperation(window.Concierge.state.operations);
    } catch (error) {
      window.Concierge.toast.error(error, "Could not load the task");
    }
  }

  taskOperation(snapshot = window.Concierge.state.operations) {
    const active = snapshot?.active;
    if (active?.kind === "task") return active;
    const latest = snapshot?.latest;
    return latest?.kind === "task" && latest.details?.task_id === this.task?.id ? latest : null;
  }

  rowsFor(operation) {
    if (operation?.progress?.task_id === this.task?.id) return operation.progress.rows;
    const start = this.checkpoint?.next_stop_index ?? 0;
    return (this.task?.stops ?? []).map((stop, index) => ({
      order: index + 1,
      poi_name: stop.poi_name,
      status: index < start ? "Completed" : "Pending",
    }));
  }

  renderOperation(snapshot, previous) {
    if (!this.task) return;
    const operation = this.taskOperation(snapshot);
    const running = operation?.status === "running";
    const rows = this.rowsFor(operation);
    this.rows.innerHTML = rows.map((row) => {
      const tone = STATUS_TONES[row.status] ?? "badge-signal badge-dot";
      const active = !STATUS_TONES[row.status];
      return `<div class="row-item ${active ? "bg-paper" : ""}"><span class="w-12 text-[13px] font-semibold">${row.order}</span><span class="w-[150px] text-[13px] font-semibold" data-name></span><span class="badge ${tone}">${row.status}</span></div>`;
    }).join("");
    this.rows.querySelectorAll("[data-name]").forEach((node, index) => { node.textContent = rows[index].poi_name; });

    const event = operation?.progress?.last_event ?? operation?.events?.at(-1);
    const done = rows.filter((row) => row.status === "Completed").length;
    this.summary.textContent = running
      ? `Stop ${Math.min(done + 1, rows.length)} of ${rows.length}`
      : operation ? operation.message : this.checkpoint ? `Can resume from stop ${this.checkpoint.next_stop_index + 1}` : "Idle.";
    this.state.hidden = !operation;
    if (operation) {
      this.state.textContent = running ? (event?.status ?? "running").replaceAll("_", " ") : operation.status;
      this.state.className = `badge ${running ? "badge-signal badge-dot" : operation.status === "failed" ? "badge-stop" : operation.status === "completed" ? "badge-ok" : "badge-neutral"}`;
    }
    if (event) {
      this.eventMeta.textContent = `${event.status} · ${window.Concierge.fmt.time(event.at)}`;
      this.eventText.textContent = event.message;
    }
    this.renderRoute(rows, running);
    if (previous?.active?.kind === "task" && !snapshot?.active && snapshot?.latest?.kind === "task") {
      window.Concierge.api.get("/api/concierge/execution").then((execution) => {
        this.checkpoint = execution.checkpoint?.task_id === this.task.id ? execution.checkpoint : null;
        this.renderButtons();
      });
    }
    this.renderButtons();
  }

  renderRoute(rows, running) {
    const pois = window.Concierge.robotStatus().pois ?? [];
    const byId = Object.fromEntries(pois.map((poi) => [poi.id, poi]));
    const points = this.task.stops
      .map((stop) => (byId[stop.poi_id] ? { ...byId[stop.poi_id].pose, name: stop.poi_name } : null))
      .filter(Boolean);
    const states = rows.map((row) => (row.status === "Completed" ? "done" : STATUS_TONES[row.status] ? "pending" : "active"));
    const progress = states.filter((state) => state === "done").length + (states.includes("active") ? 1 : 0);
    this.map.set("route", { points, states, progress, start: window.Concierge.robotStatus().home_pose, headings: true });
    const activeRow = rows.find((row) => !STATUS_TONES[row.status]);
    if (this.badge) {
      this.badge.hidden = !(running && activeRow);
      if (activeRow) this.badge.textContent = `${activeRow.status}: ${activeRow.poi_name}`;
    }
  }

  renderStatus(status) {
    this.map.set("robot", status.pose);
    this.map.set("dock", status.home_pose);
    if (this.task && !this.map.layerData.route?.points?.length && status.pois) this.renderOperation(window.Concierge.state.operations);
  }

  renderButtons() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    const running = window.Concierge.state.operations?.active?.kind === "task";
    const common = [
      c.busy, c.offline, c.noMap, c.mapping, c.unlocalized, c.unbound, c.moving,
      c.armsNotReady,
      [!this.task, "Choose a saved task"],
      [this.task && !this.speechReady, "Speech is not prepared for every stop"],
      [!this.confirm.checked, "Confirm Tianyi arm motion first"],
    ];
    gate(this.runButton, blocked(...common));
    gate(this.resumeButton, blocked(...common, [!this.checkpoint, "There is no interrupted run to resume"]));
    if (this.resumeButton.dataset.pending !== "true") {
      this.resumeButton.textContent = this.checkpoint ? `Resume from stop ${this.checkpoint.next_stop_index + 1}` : "Resume task";
    }
    gate(this.cancelButton, running ? null : "No task is running");
    this.taskSelect.disabled = running;
  }

  async run(resume) {
    const path = resume ? "/api/concierge/execution/resume" : "/api/concierge/execution/run";
    try {
      const finished = await window.Concierge.runOperation(path, { task_id: this.task.id, arms_confirmed: this.confirm.checked });
      const tone = finished.status === "completed" ? "ok" : finished.status === "cancelled" ? "caution" : "stop";
      window.Concierge.toast.show(finished.message, tone, { timeout: 10000 });
    } catch {
      /* reported */
    }
    this.confirm.checked = false;
    this.renderButtons();
  }

  async cancel() {
    try {
      const result = await window.Concierge.api.post("/api/concierge/execution/cancel");
      window.Concierge.toast.show(result.message, result.cancelled ? "caution" : "neutral");
    } catch (error) {
      window.Concierge.toast.error(error, "Cancel failed");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="task-execution"]');
  if (root) new TaskExecutionPanel(root).start();
});
