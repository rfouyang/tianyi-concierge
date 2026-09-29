class PoiPanel {
  constructor(root) {
    this.root = root;
    const q = (selector) => root.querySelector(selector);
    this.map = new window.Concierge.MapView(q("[data-map-view]"));
    this.form = q("[data-record-form]");
    this.rows = q("[data-poi-rows]");
    this.search = q("[data-poi-search]");
    this.selectedText = q("[data-poi-selected]");
    this.deleteButton = q("[data-poi-delete]");
    window.Concierge.bindLocalizationHint(root.querySelector("[data-localization-hint]"));
    this.kv = Object.fromEntries([...root.querySelectorAll("[data-kv]")].map((n) => [n.dataset.kv, n]));
    this.pois = [];
    this.selected = null;
  }

  start() {
    this.recordButton = this.form.querySelector("button[type=submit]");
    this.form.addEventListener("submit", (event) => event.preventDefault());
    this.form.name.addEventListener("input", () => this.renderButtons());
    window.Concierge.act(this.recordButton, () => this.record());
    this.search.addEventListener("input", () => this.renderRows());
    window.Concierge.act(this.deleteButton, () => this.deleteSelected());
    document.addEventListener("concierge:status", (event) => this.renderStatus(event.detail));
    document.addEventListener("concierge:busy", () => this.renderButtons());
    this.map.load();
    this.refresh();
  }

  async refresh() {
    try {
      const catalog = await window.Concierge.api.get("/api/concierge/pois");
      this.pois = catalog.pois;
      this.kv.map.textContent = catalog.map_status?.map_load_status ?? "–";
      this.kv.home.textContent = window.Concierge.fmt.pose(catalog.start_pose);
      if (this.selected && !this.pois.some((poi) => poi.id === this.selected.id)) this.selected = null;
      this.renderRows();
    } catch (error) {
      window.Concierge.toast.error(error, "Could not read POIs");
    }
  }

  renderRows() {
    const term = this.search.value.trim().toLowerCase();
    const fmt = window.Concierge.fmt;
    const visible = this.pois.filter((poi) => fmt.poiName(poi).toLowerCase().includes(term));
    this.rows.innerHTML = visible.map((poi) => {
      const selected = poi.id === this.selected?.id;
      return `<button type="button" role="option" aria-selected="${selected}" data-poi-id="${poi.id}"
          class="row-item text-left ${selected ? "bg-signal-soft" : "hover:bg-paper"}">
        <span class="flex w-[150px] flex-col"><span class="text-[13px] font-semibold"></span><span class="text-[11px] text-ink-3">${poi.id.slice(0, 8)}…</span></span>
        <span class="w-[52px] text-[13px] text-ink-2">${poi.metadata?.type ?? ""}</span>
        <span class="w-11 text-[13px] text-ink-2">${fmt.number(poi.pose?.x)}</span>
        <span class="w-11 text-[13px] text-ink-2">${fmt.number(poi.pose?.y)}</span>
        <span class="w-10 text-[13px] text-ink-2" title="${fmt.number(poi.pose?.yaw)} rad">${fmt.degrees(Number(poi.pose?.yaw ?? 0))}</span>
      </button>`;
    }).join("") || `<p class="px-2 py-6 text-center text-[13px] text-ink-3">${this.pois.length ? "No POI matches the search." : "No POIs yet. Drive Tianyi to a spot and record one."}</p>`;
    this.rows.querySelectorAll("[data-poi-id]").forEach((row, index) => {
      row.querySelector(".font-semibold").textContent = fmt.poiName(visible[index]);
      row.addEventListener("click", () => this.select(visible[index]));
    });
    this.kv.count.textContent = String(this.pois.length);
    this.map.set("pois", { pois: this.pois, selectedId: this.selected?.id, headings: true });
    this.renderButtons();
  }

  select(poi) {
    this.selected = this.selected?.id === poi.id ? null : poi;
    this.renderRows();
  }

  renderButtons() {
    const { gate, blocked, checks } = window.Concierge;
    const c = checks();
    const name = this.form.name.value.trim();
    const taken = this.pois.some((poi) => window.Concierge.fmt.poiName(poi).toLowerCase() === name.toLowerCase());
    gate(this.recordButton, blocked(
      c.busy, c.offline, c.noMap, c.unlocalized, c.moving,
      [!name, "Enter a name for the POI"],
      [taken, `A POI named ${name} already exists`],
    ));
    gate(this.deleteButton, blocked(c.busy, c.offline, [!this.selected, "Select a POI first"]));
    this.selectedText.textContent = this.selected
      ? `Selected: ${window.Concierge.fmt.poiName(this.selected)}`
      : "Select a POI to delete it.";
  }

  renderStatus(status) {
    this.map.set("robot", status.pose);
    this.map.set("dock", status.home_pose);
    const quality = status.quality;
    this.kv.quality.textContent = typeof quality === "number" ? `${quality} / 100` : "–";
    this.kv.quality.classList.toggle("text-ok", quality >= 50);
    this.kv.quality.classList.toggle("text-caution", quality < 50);
    this.kv.pose.textContent = window.Concierge.fmt.pose(status.pose);
  }

  async record() {
    const name = this.form.name.value.trim();
    if (!name) return;
    try {
      await window.Concierge.runOperation("/api/concierge/pois", { name }, {
        success: `Recorded POI ${name}. The map was saved on the robot.`,
      });
      this.form.name.value = "";
    } catch {
      /* reported */
    }
    this.refresh();
  }

  async deleteSelected() {
    const poi = this.selected;
    if (!poi) return;
    const name = window.Concierge.fmt.poiName(poi);
    if (!window.confirm(`Delete POI ${name}? Tasks that visit it will need a new POI.`)) return;
    try {
      const operation = await window.Concierge.api.delete(`/api/concierge/pois/${encodeURIComponent(poi.id)}`);
      await window.Concierge.waitForOperation(operation.id);
      window.Concierge.toast.show(`Deleted POI ${name}.`, "ok");
      this.selected = null;
    } catch (error) {
      window.Concierge.toast.error(error, "Delete POI failed");
    }
    this.refresh();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector('[data-panel="pois"]');
  if (root) new PoiPanel(root).start();
});
