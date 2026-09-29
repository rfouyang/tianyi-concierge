const NAVIGATION_KINDS = { navigation_go: "Go to POI", navigation_home: "Go home", navigation_undock: "Undock" };

class NavigationPanel {
  constructor(root) {
    this.root = root;
    const q = (selector) => root.querySelector(selector);
    this.map = new window.Concierge.MapView(q("[data-map-view]"));
    this.list = q("[data-nav-pois]");
    this.speech = q("[data-nav-speech]");
    this.speechHint = q("[data-nav-speech-hint]");
    this.goButton = q("[data-nav-go]");
    this.homeButton = q("[data-nav-home]");
    this.undockButton = q("[data-nav-undock]");
    this.badge = document.getElementById("nav-badge");
    window.Concierge.bindLocalizationHint(root.querySelector("[data-localization-hint]"));
    this.kv = Object.fromEntries([...root.querySelectorAll("[data-kv]")].map((n) => [n.dataset.kv, n]));
    this.pois = [];
    this.selected = null;
    this.stopContent = new Map();
  }

  start() {
    const { act } = window.Concierge;
    act(this.goButton, () => this.go());
    act(this.homeButton, () => this.run("/api/concierge/navigation/home", "Tianyi is docked and charging."));
    act(this.undockButton, () => this.run("/api/concierge/navigation/undock", "Tianyi left the dock."));
    this.list.addEventListener("click", (event) => {
      const row = event.target.closest("[data-id]");
      const poi = row && this.pois.find((item) => item.id === row.dataset.id);
      if (poi) this.select(poi);
    });
    document.addEventListener("concierge:status", (event) => this.renderStatus(event.detail));
    document.addEventListener("concierge:operations", (event) => this.renderOperation(event.detail.current));
    document.addEventListener("concierge:busy", () => this.renderButtons());
    this.map.load();
    this.loadTaskSpeech();
  }

  /** Prefill arrival speech from the first saved task stop for each POI. */
  async loadTaskSpeech() {
    try {
      const { tasks } = await window.Concierge.api.get("/api/concierge/tasks");
      for (const task of tasks) {
        for (const stop of task.stops) if (!this.stopContent.has(stop.poi_id)) this.stopContent.set(stop.poi_id, stop.content);
      }
    } catch {
      /* speech stays empty; the robot then says "You have arrived at ..." */
    }
  }

  renderStatus(status) {
    this.map.set("robot", status.pose);
    this.map.set("dock", status.home_pose);
    if (status.pois && JSON.stringify(status.pois) !== JSON.stringify(this.pois)) {
      this.pois = [...status.pois].sort((a, b) => window.Concierge.fmt.poiName(a).localeCompare(window.Concierge.fmt.poiName(b)));
      this.renderList();
    }
    this.renderTarget();
  }

  renderList() {
    const fmt = window.Concierge.fmt;
    const running = this.runningTarget();
    const html = this.pois.map((poi) => {
      const selected = poi.id === this.selected?.id;
      return `<button type="button" role="option" aria-selected="${selected}" data-id="${fmt.escape(poi.id)}"
        class="flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm ${selected ? "border-signal bg-signal-soft font-semibold text-signal-ink" : "border-line hover:bg-paper"}">
        <span class="flex-1">${fmt.escape(fmt.poiName(poi))}</span>
        ${running === poi.id ? '<span class="badge badge-signal badge-dot">Navigating</span>' : `<span class="text-[11px] text-ink-3">${fmt.escape(poi.metadata?.type ?? "")}</span>`}
      </button>`;
    }).join("") || '<p class="py-4 text-center text-[13px] text-ink-3">No POIs on the loaded map.</p>';
    window.Concierge.renderHtml(this.list, html);
    this.map.set("pois", { pois: this.pois, selectedId: this.selected?.id, headings: true });
    this.renderButtons();
  }

  select(poi) {
    this.selected = poi;
    const content = this.stopContent.get(poi.id) ?? "";
    this.speech.value = content;
    this.speechHint.textContent = content
      ? "Prefilled from the saved task stop for this POI."
      : `No task stop uses this POI. If empty, Tianyi says “You have arrived at ${window.Concierge.fmt.poiName(poi)}.”`;
    this.renderList();
  }

  runningTarget() {
    const active = window.Concierge.state.operations?.active;
    return active?.kind === "navigation_go" ? active.details?.poi_id : null;
  }

  renderTarget() {
    const targetId = this.runningTarget();
    const target = this.pois.find((poi) => poi.id === targetId);
    this.map.set("path", target ? { from: window.Concierge.robotStatus().pose, to: target.pose } : null);
    if (this.badge) {
      this.badge.hidden = !target;
      if (target) this.badge.textContent = `Navigating to ${window.Concierge.fmt.poiName(target)}`;
    }
  }

  renderOperation(snapshot) {
    const operation = [snapshot?.active, snapshot?.latest].find((item) => item && NAVIGATION_KINDS[item.kind]);
    if (operation) {
      this.kv.action.textContent = NAVIGATION_KINDS[operation.kind];
      this.kv.status.textContent = operation.status;
      this.kv.status.classList.toggle("text-signal", operation.status === "running");
      this.kv.status.classList.toggle("text-stop", operation.status === "failed");
      this.kv.message.textContent = operation.error || operation.message || "";
    }
    this.renderList();
    this.renderTarget();
  }

  renderButtons() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    gate(this.goButton, blocked(
      c.busy, c.offline, c.noMap, c.mapping, c.unlocalized, c.moving,
      [!this.selected, "Select a POI first"],
    ));
    gate(this.homeButton, blocked(
      c.busy, c.offline, c.noMap, c.mapping, c.unlocalized, c.moving, c.unbound,
      [!c.offDock[0], "Tianyi is already on the charging dock"],
    ));
    gate(this.undockButton, blocked(c.busy, c.offline, c.moving, c.offDock));
  }

  async go() {
    const poi = this.selected;
    const name = window.Concierge.fmt.poiName(poi);
    try {
      const finished = await window.Concierge.runOperation(
        "/api/concierge/navigation/go",
        { poi_id: poi.id, content: this.speech.value.trim() || null },
      );
      window.Concierge.toast.show(
        finished.result?.status === "stopped" ? `Navigation stopped; Tianyi stays where it is.` : `Arrived at ${name} and spoke.`,
        finished.result?.status === "stopped" ? "caution" : "ok",
      );
    } catch {
      /* reported */
    }
  }

  async run(path, success) {
    try {
      await window.Concierge.runOperation(path, {}, { success });
    } catch {
      /* reported */
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="navigation"]');
  if (root) new NavigationPanel(root).start();
});
