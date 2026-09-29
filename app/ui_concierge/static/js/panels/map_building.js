class MapBuildingPanel {
  constructor(root) {
    this.root = root;
    this.form = root.querySelector("[data-build-form]");
    this.startButton = root.querySelector("[data-build-start]");
    this.finishButton = root.querySelector("[data-build-finish]");
    this.stopExistingButton = root.querySelector("[data-build-stop-existing]");
    this.badge = root.querySelector("[data-build-badge]");
    this.kv = Object.fromEntries([...root.querySelectorAll("[data-kv]")].map((n) => [n.dataset.kv, n]));
    this.map = new window.Concierge.MapView(root.querySelector("[data-map-view]"));
    this.session = null;
  }

  start() {
    const { act } = window.Concierge;
    this.form.addEventListener("submit", (event) => event.preventDefault());
    this.form.addEventListener("input", () => this.renderButtons());
    act(this.startButton, () => this.startBuild());
    act(this.finishButton, () => this.finishBuild());
    act(this.stopExistingButton, () => this.stopExisting());
    document.addEventListener("concierge:status", (event) => this.renderStatus(event.detail));
    document.addEventListener("concierge:busy", () => this.renderButtons());
    this.map.load();
    this.refresh();
  }

  async refresh() {
    try {
      const status = await window.Concierge.api.get("/api/concierge/map-building");
      this.session = status.session;
      this.renderSession();
    } catch (error) {
      window.Concierge.toast.error(error, "Could not read the map-building state");
    }
  }

  get building() {
    return Boolean(this.session?.active);
  }

  renderButtons() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    const mapping = Boolean(c.status.mapping);
    gate(this.startButton, blocked(
      c.busy,
      c.offline,
      [this.building, "A map build is already running"],
      c.mapping,
      c.offDock,
      c.notCharging,
      [!this.form.filename.value.trim().toLowerCase().endsWith(".stcm"), "Enter a .stcm map filename"],
      [!this.form.dock_name.value.trim(), "Enter the charging dock name"],
      [!this.form.confirmed.checked, "Confirm that Start clears the in-memory map"],
    ));
    gate(this.finishButton, blocked(c.busy, [!this.building, "No map build is running"]));
    gate(this.stopExistingButton, blocked(
      c.busy,
      [this.building, "Use Finish and save for this build"],
      [!mapping, "No mapping is running"],
    ));
    this.badge.hidden = !mapping;
  }

  renderSession() {
    const session = this.session;
    this.kv.start_pose.textContent = window.Concierge.fmt.pose(session?.start_pose);
    this.kv.home_dock.textContent = session?.home_dock?.metadata?.display_name ?? session?.home_dock?.id ?? "–";
    this.kv.map_path.textContent = session && !session.active && session.map_path ? session.map_path.split("/").slice(-3).join("/") : "–";
    this.map.set("start", session?.start_pose ?? null);
    this.renderButtons();
  }

  renderStatus(status) {
    const power = status.power ?? {};
    this.kv.mapping.textContent = status.mapping ? "Active" : "Stopped";
    this.kv.mapping.classList.toggle("text-signal", Boolean(status.mapping));
    this.kv.battery.textContent = typeof power.batteryPercentage === "number" ? `${power.batteryPercentage}%` : "–";
    this.kv.dock.textContent = power.dockingStatus === "on_dock" ? "On dock" : "Not on dock";
    this.kv.charging.textContent = power.isCharging ? "Yes" : "No";
    this.kv.pose.textContent = window.Concierge.fmt.pose(status.pose);
    this.map.set("robot", status.pose);
    this.map.set("dock", this.session?.home_dock?.pose ?? status.home_pose);
    this.renderButtons();
  }

  async startBuild() {
    const data = new FormData(this.form);
    try {
      await window.Concierge.runOperation(
        "/api/concierge/map-building/start",
        {
          filename: data.get("filename"),
          dock_name: data.get("dock_name"),
          overwrite: data.get("overwrite") === "on",
          confirmed: data.get("confirmed") === "on",
        },
        { success: "Mapping started. Drive Tianyi slowly and close loops back to the dock." },
      );
    } catch {
      /* reported by runOperation */
    }
    this.form.confirmed.checked = false;
    this.refresh();
  }

  async finishBuild() {
    try {
      await window.Concierge.runOperation(
        "/api/concierge/map-building/finish",
        { overwrite: this.form.overwrite.checked },
        { success: (op) => `Map saved on the robot and to ${op.result?.map_path?.split("/").slice(-3).join("/")}.` },
      );
    } catch {
      /* reported by runOperation */
    }
    this.refresh();
  }

  async stopExisting() {
    try {
      await window.Concierge.runOperation("/api/concierge/map-building/stop-existing", {}, {
        success: "Mapping paused. Its in-memory map was not cleared or saved.",
      });
    } catch {
      /* reported by runOperation */
    }
    this.refresh();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="map-building"]');
  if (root) new MapBuildingPanel(root).start();
});
