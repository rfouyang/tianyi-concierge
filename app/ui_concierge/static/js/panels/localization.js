class LocalizationPanel {
  constructor(root) {
    this.root = root;
    const q = (selector) => root.querySelector(selector);
    this.map = new window.Concierge.MapView(q("[data-map-view]"));
    this.mapSelect = q("[data-map-select]");
    this.loadButton = q("[data-load-map]");
    this.loadConfirm = q("[data-load-confirm]");
    this.loadLock = q("[data-load-lock]");
    this.loadHint = q("[data-load-hint]");
    this.currentMap = q("[data-current-map]");
    this.currentBadge = q("[data-current-map-badge]");
    this.qualityBadge = q("[data-quality-badge]");
    this.modeButtons = [...root.querySelectorAll("[data-mode]")];
    this.modePanels = [...root.querySelectorAll("[data-mode-panel]")];
    this.dockChecks = q("[data-dock-checks]");
    this.dockButton = q("[data-localize-dock]");
    this.arrowButton = q("[data-localize-arrow]");
    this.arrowReset = q("[data-arrow-reset]");
    this.arrowFields = Object.fromEntries([...root.querySelectorAll("[data-arrow]")].map((n) => [n.dataset.arrow, n]));
    this.searchSize = q("[data-search-size]");
    this.allowRotation = q("[data-allow-rotation]");
    this.stopButton = q("[data-stop-localization]");
    this.syncButton = q("[data-sync-map]");
    this.unbound = q("[data-unbound]");
    this.bindButton = q("[data-bind-dock]");
    this.snapshotButton = q("[data-snapshot]");
    this.mode = "dock";
    this.stateDot = q("[data-state-dot]");
    this.stateLabel = q("[data-state-label]");
    this.stateDetail = q("[data-state-detail]");
    this.arrowPose = null;
    this.arrowTouched = false;
  }

  start() {
    const { act } = window.Concierge;
    this.loadConfirm.addEventListener("change", () => this.render());
    this.mapSelect.addEventListener("change", () => this.render());
    act(this.loadButton, () => this.loadMap());
    for (const button of this.modeButtons) button.addEventListener("click", () => this.setMode(button.dataset.mode));
    act(this.dockButton, () => this.localizeAtDock());
    act(this.arrowButton, () => this.localizeAtArrow());
    act(this.bindButton, () => this.bindDock());
    this.arrowReset.addEventListener("click", () => this.resetArrow());
    this.searchSize.addEventListener("change", () => {
      const half = Number(this.searchSize.value);
      this.arrowFields.area.textContent = `${half * 2} × ${half * 2} m`;
      this.map.setArrowSearchSize(half);
    });
    act(this.stopButton, () => this.stopLocalization());
    act(this.syncButton, () => this.syncMap());
    act(this.snapshotButton, () => this.saveSnapshot());
    document.addEventListener("concierge:status", (event) => this.renderStatus(event.detail));
    document.addEventListener("concierge:busy", () => this.render());
    this.map.load().then(() => this.setMode(this.mode));
    this.refreshMaps();
    this.refreshIdentity();
  }

  status() {
    return window.Concierge.robotStatus();
  }

  get locked() {
    return this.status().localization_enabled !== false;
  }

  async refreshMaps() {
    try {
      const { maps } = await window.Concierge.api.get("/api/concierge/maps");
      const current = this.mapSelect.value;
      this.mapSelect.innerHTML = maps.map((item) => `<option value="${item.name}">${item.name}</option>`).join("");
      if (maps.some((item) => item.name === current)) this.mapSelect.value = current;
      this.render();
    } catch (error) {
      window.Concierge.toast.error(error, "Could not list data/maps");
    }
  }

  async refreshIdentity() {
    this.currentMap.textContent = "Identifying…";
    try {
      const identity = await window.Concierge.api.get("/api/concierge/maps/current");
      this.currentMap.textContent = identity.display_name;
      this.currentBadge.hidden = !identity.verified;
    } catch (error) {
      this.currentMap.textContent = "Unknown";
      this.currentBadge.hidden = true;
    }
  }

  setMode(mode) {
    this.mode = mode;
    for (const button of this.modeButtons) button.setAttribute("aria-selected", String(button.dataset.mode === mode));
    for (const panel of this.modePanels) panel.hidden = panel.dataset.modePanel !== mode;
    if (mode === "arrow" && this.map.meta) {
      this.map.enableArrow(this.arrowPose ?? this.defaultArrowPose(), (pose, meta) => this.renderArrow(pose, meta));
      this.map.setArrowSearchSize(Number(this.searchSize.value));
    } else {
      this.map.disableArrow();
    }
    this.render();
  }

  defaultArrowPose() {
    const pose = this.status().pose;
    if (typeof pose?.x === "number") return { x: pose.x, y: pose.y, yaw: pose.yaw ?? 0 };
    const meta = this.map.meta;
    return { ...this.map.toWorld(meta.width / 2, meta.height / 2), yaw: 0 };
  }

  resetArrow() {
    this.arrowPose = null;
    this.arrowTouched = false;
    this.setMode("arrow");
  }

  renderArrow(pose, { touched = true } = {}) {
    if (touched && this.arrowPose) this.arrowTouched = true;
    this.arrowPose = { ...pose };
    const fmt = window.Concierge.fmt;
    this.arrowFields.x.textContent = `${fmt.number(pose.x)} m`;
    this.arrowFields.y.textContent = `${fmt.number(pose.y)} m`;
    this.arrowFields.yaw.textContent = fmt.degrees(pose.yaw ?? 0);
  }

  renderStatus(status) {
    const firstPose = !this.hasPose && typeof status.pose?.x === "number";
    this.hasPose = this.hasPose || firstPose;
    if (firstPose && this.mode === "arrow" && !this.arrowTouched && this.map.meta) {
      this.arrowPose = null;
      this.setMode("arrow");
    }
    this.map.set("robot", status.pose);
    this.map.set("dock", status.home_pose);
    if (status.pois) this.map.set("pois", { pois: status.pois });
    this.renderState(status.localization_state);
    const quality = status.quality;
    const good = typeof quality === "number" && quality >= 50;
    this.qualityBadge.textContent = status.localization_enabled === false ? "Localization stopped" : `Quality ${quality ?? "–"} / 100`;
    this.qualityBadge.className = `badge ${status.localization_enabled === false ? "badge-neutral" : good ? "badge-ok" : "badge-caution"}`;
    this.renderDockChecks(status);
    this.render();
  }

  renderState(state) {
    const [label, tone] = window.Concierge.localizationLabel(state);
    this.stateLabel.textContent = label;
    this.stateDot.className = `size-3 shrink-0 rounded-full ${{ ok: "bg-ok", caution: "bg-caution animate-pulse", stop: "bg-stop" }[tone]}`;
    const method = { dock: "at the charging dock", pose: "at a placed pose" }[state?.method];
    this.stateDetail.textContent = state?.state === "localized"
      ? `Localized ${method ?? ""} at ${window.Concierge.fmt.time(state.localized_at)}. Navigation and tours can start.`
      : `${state?.reason ?? ""}. Navigation and tours stay locked until Tianyi is localized.`;
  }

  dockConditions(status) {
    const power = status.power ?? {};
    const mapStatus = status.map_status ?? {};
    return [
      ["On the charging dock", power.dockingStatus === "on_dock"],
      ["Home dock bound", Boolean(mapStatus.is_homedock_binded)],
      ["Map loaded", mapStatus.map_load_status === "LOADED"],
      ["No motion or mapping running", !status.current_action && !status.mapping],
    ];
  }

  renderDockChecks(status) {
    const html = this.dockConditions(status).map(([label, ok]) =>
      `<li class="flex items-center gap-2.5"><span class="grid size-[18px] shrink-0 place-items-center rounded-full ${ok ? "bg-ok" : "bg-stop"} text-[11px] font-bold text-white">${ok ? "✓" : "✕"}</span>${label}</li>`,
    ).join("");
    window.Concierge.renderHtml(this.dockChecks, html);
  }

  async bindDock() {
    if (!window.confirm("Bind the map's charging dock as Tianyi's home dock? Tianyi must be on the dock.")) return;
    try {
      await window.Concierge.runOperation("/api/concierge/localization/bind-dock", { confirmed: true }, {
        success: (op) => `Bound charging dock ${op.result?.dock_name ?? op.result?.id}. Tours can return home again.`,
      });
    } catch {
      /* reported */
    }
  }

  render() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    const locked = this.locked;
    this.loadLock.hidden = !locked;
    this.loadHint.textContent = locked
      ? "Localization is running. Stop localization to load a different map."
      : "Requires Tianyi docked, charging and idle. Loading reloads at the charging dock.";
    this.loadConfirm.disabled = locked;
    gate(this.loadButton, blocked(
      c.busy, c.offline,
      [locked, "Stop localization before loading a map"],
      c.mapping, c.moving, c.offDock, c.notCharging,
      [!this.mapSelect.value, "Choose a map from data/maps"],
      [!this.loadConfirm.checked, "Confirm that this map replaces the stored robot map"],
    ));
    const unbound = c.unbound[0] && !c.noMap[0];
    this.unbound.hidden = !unbound;
    gate(this.bindButton, blocked(c.busy, c.offline, c.mapping, c.moving, c.offDock));
    gate(this.dockButton, blocked(c.busy, c.offline, c.noMap, c.mapping, c.moving, c.offDock, c.unbound));
    gate(this.arrowButton, blocked(
      c.busy, c.offline, c.noMap, c.mapping, c.moving,
      [!this.arrowPose, "Place the arrow on the map first"],
    ));
    gate(this.stopButton, blocked(c.busy, c.moving, [!locked, "Localization is already stopped"]));
    gate(this.syncButton, blocked(c.busy, c.offline, c.mapping, c.moving, c.offDock, c.notCharging));
    gate(this.snapshotButton, blocked(c.busy, c.offline, c.noMap));
  }

  async loadMap() {
    const name = this.mapSelect.value;
    try {
      await window.Concierge.runOperation(
        "/api/concierge/maps/load",
        { name, confirmed: this.loadConfirm.checked },
        { success: `data/maps/${name} is on robot storage, reloaded and verified.` },
      );
    } catch {
      /* reported */
    }
    this.loadConfirm.checked = false;
    this.refreshIdentity();
    this.render();
  }

  async localizeAtDock() {
    try {
      await window.Concierge.runOperation("/api/concierge/localization/dock", {}, {
        success: (op) => `Localized at the charging dock. Quality ${op.result?.quality}.${op.result?.dock_rebound ? " The dock binding was restored." : ""}`,
      });
    } catch {
      /* reported */
    }
  }

  async localizeAtArrow() {
    const pose = this.arrowPose;
    const allowRotation = this.allowRotation.checked;
    try {
      await window.Concierge.runOperation(
        "/api/concierge/localization/pose",
        {
          x: pose.x,
          y: pose.y,
          yaw: pose.yaw ?? 0,
          search_half_size: Number(this.searchSize.value),
          allow_rotation: allowRotation,
          rotation_confirmed: allowRotation,
        },
        { success: (op) => `Localized at the arrow. Quality ${op.result?.quality}.` },
      );
      this.arrowPose = null;
    } catch {
      /* reported */
    }
  }

  async stopLocalization() {
    try {
      await window.Concierge.runOperation("/api/concierge/localization/stop", {}, {
        success: "Localization stopped. You can load a different map now.",
      });
    } catch {
      /* reported */
    }
  }

  async syncMap() {
    if (!window.confirm("Sync saves the robot's in-memory map to its storage and reloads it at the dock. Continue?")) return;
    try {
      await window.Concierge.runOperation("/api/concierge/maps/sync", { confirmed: true }, {
        success: "The in-memory map was saved to robot storage and reloaded.",
      });
    } catch {
      /* reported */
    }
    this.refreshIdentity();
  }

  async saveSnapshot() {
    const filename = window.prompt("Save the robot map to data/maps as:", "robot_map.stcm");
    if (!filename) return;
    try {
      await window.Concierge.runOperation("/api/concierge/maps/snapshot", { filename, overwrite: false }, {
        success: `Saved data/maps/${filename}.`,
      });
    } catch {
      /* reported */
    }
    this.refreshMaps();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="localization"]');
  if (root) new LocalizationPanel(root).start();
});
