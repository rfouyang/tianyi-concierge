const MAP_COLORS = {
  ink: "#1c2430",
  ink3: "#7b8794",
  signal: "#0f766e",
  ok: "#2f7d32",
  poi: "#6d4aa8",
  start: "#2563eb",
  white: "#ffffff",
};
const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * The robot's explore map with SVG overlays. World coordinates (metres, yaw in
 * radians) are converted with the grid origin and resolution from the server.
 */
class MapView {
  constructor(root) {
    this.root = root;
    this.stage = root.querySelector("[data-map-stage]");
    this.image = root.querySelector("[data-map-image]");
    this.svg = root.querySelector("[data-map-overlay]");
    this.empty = root.querySelector("[data-map-empty]");
    this.meta = null;
    this.layers = {};
    this.layerData = {};
    this.arrow = null;
    new ResizeObserver(() => this.fit()).observe(root);
    document.addEventListener("concierge:status", (event) => {
      const revision = event.detail.map?.revision;
      if (revision && revision !== this.meta?.revision) this.load();
    });
  }

  async load() {
    try {
      const meta = await window.Concierge.api.get("/api/concierge/maps/view");
      this.meta = meta;
      this.svg.setAttribute("viewBox", `0 0 ${meta.width} ${meta.height}`);
      this.image.src = `/api/concierge/maps/view.png?rev=${meta.revision}`;
      this.empty.hidden = true;
      this.fit();
      this.redraw();
    } catch (error) {
      this.empty.hidden = false;
      this.empty.textContent = `Map unavailable: ${error.message}`;
    }
  }

  fit() {
    if (!this.meta) return;
    const box = this.root.getBoundingClientRect();
    const ratio = this.meta.width / this.meta.height;
    let width = box.width;
    let height = width / ratio;
    if (height > box.height) {
      height = box.height;
      width = height * ratio;
    }
    this.stage.style.width = `${width}px`;
    this.stage.style.height = `${height}px`;
    this.stage.style.marginTop = `${Math.max(0, (box.height - height) / 2)}px`;
    this.redraw();
  }

  /** Screen-constant size: convert CSS pixels into map pixels. */
  px(size) {
    const width = this.stage.getBoundingClientRect().width || 1;
    return (size * this.meta.width) / width;
  }

  toMap(point) {
    const m = this.meta;
    return [
      (point.x - m.origin_x) / m.resolution,
      m.height - 1 - (point.y - m.origin_y) / m.resolution,
    ];
  }

  toWorld(mapX, mapY) {
    const m = this.meta;
    return {
      x: m.origin_x + mapX * m.resolution,
      y: m.origin_y + (m.height - 1 - mapY) * m.resolution,
    };
  }

  layer(name) {
    if (!this.layers[name]) {
      const group = document.createElementNS(SVG_NS, "g");
      group.dataset.layer = name;
      const order = ["route", "path", "pois", "start", "dock", "target", "robot", "arrow"];
      const index = order.indexOf(name);
      const next = [...this.svg.children].find((child) => order.indexOf(child.dataset.layer) > index);
      this.svg.insertBefore(group, next ?? null);
      this.layers[name] = group;
    }
    return this.layers[name];
  }

  set(name, data) {
    this.layerData[name] = data;
    this.draw(name);
  }

  redraw() {
    if (!this.meta) return;
    for (const name of Object.keys(this.layerData)) this.draw(name);
    if (this.arrow) this.drawArrow();
  }

  draw(name) {
    if (!this.meta) return;
    const group = this.layer(name);
    const data = this.layerData[name];
    group.innerHTML = data ? this[`render_${name}`](data) : "";
  }

  render_robot(pose) {
    if (typeof pose?.x !== "number") return "";
    const [x, y] = this.toMap(pose);
    const r = this.px(11);
    const angle = (-(pose.yaw ?? 0) * 180) / Math.PI;
    const tip = this.px(8);
    return `<circle cx="${x}" cy="${y}" r="${this.px(22)}" fill="${MAP_COLORS.signal}" fill-opacity="0.18"/>
      <g transform="translate(${x} ${y}) rotate(${angle})">
        <circle r="${r}" fill="${MAP_COLORS.signal}" stroke="${MAP_COLORS.white}" stroke-width="${this.px(3)}"/>
        <path d="M${tip} 0 L${-tip * 0.6} ${-tip * 0.7} L${-tip * 0.2} 0 L${-tip * 0.6} ${tip * 0.7} Z" fill="${MAP_COLORS.white}"/>
      </g>`;
  }

  render_dock(pose) {
    if (typeof pose?.x !== "number") return "";
    const [x, y] = this.toMap(pose);
    const s = this.px(24);
    return `<rect x="${x - s / 2}" y="${y - s / 2}" width="${s}" height="${s}" rx="${this.px(6)}" fill="${MAP_COLORS.ok}"/>
      <path d="M${x - s * 0.15} ${y - s * 0.28}v${s * 0.2}M${x + s * 0.15} ${y - s * 0.28}v${s * 0.2}M${x - s * 0.25} ${y - s * 0.08}h${s * 0.5}v${s * 0.12}a${s * 0.25} ${s * 0.25} 0 0 1 ${-s * 0.5} 0z" stroke="${MAP_COLORS.white}" stroke-width="${this.px(2)}" fill="none"/>`;
  }

  render_start(pose) {
    if (typeof pose?.x !== "number") return "";
    const [x, y] = this.toMap(pose);
    return `<circle cx="${x}" cy="${y}" r="${this.px(7)}" fill="${MAP_COLORS.start}" stroke="${MAP_COLORS.white}" stroke-width="${this.px(2)}"/>`;
  }

  label(x, y, text, offset, alignRight) {
    const size = this.px(12);
    const width = this.px(text.length * 7 + 14);
    const height = this.px(22);
    const left = alignRight ? x - offset - width : x + offset;
    const safe = text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    return `<rect x="${left}" y="${y - height / 2}" width="${width}" height="${height}" rx="${this.px(6)}" fill="${MAP_COLORS.white}" stroke="#dce2e6" stroke-width="${this.px(1)}"/>
      <text x="${left + width / 2}" y="${y + size * 0.36}" font-size="${size}" font-weight="600" text-anchor="middle" fill="${MAP_COLORS.ink}" font-family="IBM Plex Sans, sans-serif">${safe}</text>`;
  }

  labelOnLeft(x) {
    return x > this.meta.width * 0.7;
  }

  /** ``{ pois, selectedId }`` as purple dots with name labels. */
  /**
   * One POI marker, identical on every page: purple dot, heading arrow, and a
   * "name · yaw" label. ``selected`` adds the teal ring (chosen or current stop).
   */
  poiMarker(pose, name, { selected = false, headings = true } = {}) {
    const fmt = window.Concierge.fmt;
    const [x, y] = this.toMap(pose);
    const yaw = Number(pose.yaw ?? 0);
    const text = headings ? `${name} · ${fmt.degrees(yaw)}` : name;
    return `${headings ? this.headingArrow(x, y, yaw, selected) : ""}
      <circle cx="${x}" cy="${y}" r="${this.px(selected ? 10 : 8)}" fill="${MAP_COLORS.poi}" stroke="${MAP_COLORS.white}" stroke-width="${this.px(2)}"/>
      ${selected ? `<circle cx="${x}" cy="${y}" r="${this.px(16)}" fill="none" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(2)}"/>` : ""}
      ${this.label(x, y, text, this.px(headings ? 18 : 14), this.labelOnLeft(x))}`;
  }

  /** ``{ pois, selectedId, headings }`` */
  render_pois({ pois, selectedId, headings = true }) {
    const fmt = window.Concierge.fmt;
    return (pois ?? [])
      .filter((poi) => typeof poi.pose?.x === "number")
      .map((poi) => this.poiMarker(poi.pose, fmt.poiName(poi), { selected: poi.id === selectedId, headings }))
      .join("");
  }

  /** The direction Tianyi faces at a POI (map y points down, so the angle is -yaw). */
  headingArrow(x, y, yaw, selected, { color, start = 0, length = 26 } = {}) {
    color = color ?? (selected ? MAP_COLORS.signal : MAP_COLORS.poi);
    const from = this.px(start);
    length = this.px(length);
    const head = this.px(7);
    const angle = (-yaw * 180) / Math.PI;
    return `<g transform="translate(${x} ${y}) rotate(${angle})">
        <path d="M${from} 0 L${length} 0" stroke="${color}" stroke-width="${this.px(3)}" stroke-linecap="round"/>
        <path d="M${length + head * 0.4} 0 L${length - head} ${-head * 0.8} L${length - head} ${head * 0.8} Z" fill="${color}"/>
      </g>`;
  }

  /**
   * ``{ points: [{x,y,yaw,name}], states: ["done"|"active"|"pending"], progress, start }``.
   * Stops use the shared POI marker, numbered in visit order; walked legs are solid.
   */
  render_route({ points, states = [], progress = 0, start, headings = true }) {
    const all = start ? [start, ...points] : points;
    let lines = "";
    for (let index = 0; index < all.length - 1; index += 1) {
      const [x1, y1] = this.toMap(all[index]);
      const [x2, y2] = this.toMap(all[index + 1]);
      const done = index < progress;
      lines += `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${done ? MAP_COLORS.signal : MAP_COLORS.ink3}" stroke-width="${this.px(done ? 4 : 2.5)}" stroke-linecap="round" ${done ? "" : `stroke-dasharray="${this.px(7)} ${this.px(7)}"`}/>`;
    }
    const markers = points
      .map((point, index) =>
        this.poiMarker(point, `${index + 1}. ${point.name ?? ""}`, {
          selected: states[index] === "active",
          headings,
        }),
      )
      .join("");
    return lines + markers;
  }

  /** A dashed line from the robot to a navigation target. */
  render_path({ from, to }) {
    if (typeof from?.x !== "number" || typeof to?.x !== "number") return "";
    const [x1, y1] = this.toMap(from);
    const [x2, y2] = this.toMap(to);
    return `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(3)}" stroke-dasharray="${this.px(6)} ${this.px(6)}" stroke-linecap="round"/>`;
  }

  // ------------------------------------------------------ drag-to-localize
  enableArrow(pose, onChange) {
    this.arrow = { pose: { ...pose }, onChange, halfSize: this.arrow?.halfSize ?? 1 };
    this.svg.style.pointerEvents = "auto";
    this.svg.style.touchAction = "none";
    if (!this.arrowBound) {
      this.arrowBound = true;
      this.svg.addEventListener("pointerdown", (event) => this.startDrag(event));
      this.svg.addEventListener("pointermove", (event) => this.moveDrag(event));
      this.svg.addEventListener("pointerup", () => this.endDrag());
      this.svg.addEventListener("pointercancel", () => this.endDrag());
    }
    this.drawArrow();
    onChange(this.arrow.pose, { touched: false });
  }

  disableArrow() {
    this.arrow = null;
    this.svg.style.pointerEvents = "";
    this.layer("arrow").innerHTML = "";
  }

  setArrowSearchSize(halfSize) {
    if (!this.arrow) return;
    this.arrow.halfSize = halfSize;
    this.drawArrow();
  }

  eventPoint(event) {
    const rect = this.svg.getBoundingClientRect();
    return [
      ((event.clientX - rect.left) / rect.width) * this.meta.width,
      ((event.clientY - rect.top) / rect.height) * this.meta.height,
    ];
  }

  startDrag(event) {
    if (!this.arrow || !this.meta) return;
    const [px, py] = this.eventPoint(event);
    const [ax, ay] = this.toMap(this.arrow.pose);
    const handle = this.handlePoint();
    const nearHandle = Math.hypot(px - handle[0], py - handle[1]) < this.px(18);
    const nearBase = Math.hypot(px - ax, py - ay) < this.px(22);
    this.drag = nearHandle ? "rotate" : nearBase ? "move" : "move";
    if (!nearHandle && !nearBase) this.setArrowFromMap(px, py);
    this.svg.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  moveDrag(event) {
    if (!this.drag || !this.arrow) return;
    const [px, py] = this.eventPoint(event);
    if (this.drag === "move") {
      this.setArrowFromMap(px, py);
    } else {
      const [ax, ay] = this.toMap(this.arrow.pose);
      this.arrow.pose.yaw = Math.atan2(-(py - ay), px - ax);
      this.drawArrow();
      this.arrow.onChange(this.arrow.pose);
    }
  }

  endDrag() {
    this.drag = null;
  }

  setArrowFromMap(px, py) {
    const world = this.toWorld(px, py);
    this.arrow.pose.x = world.x;
    this.arrow.pose.y = world.y;
    this.drawArrow();
    this.arrow.onChange(this.arrow.pose);
  }

  handlePoint() {
    const [ax, ay] = this.toMap(this.arrow.pose);
    const length = this.px(62);
    const yaw = this.arrow.pose.yaw ?? 0;
    return [ax + Math.cos(yaw) * length, ay - Math.sin(yaw) * length];
  }

  drawArrow() {
    if (!this.arrow || !this.meta) return;
    const [ax, ay] = this.toMap(this.arrow.pose);
    const [hx, hy] = this.handlePoint();
    const radius = this.arrow.halfSize / this.meta.resolution;
    const yaw = this.arrow.pose.yaw ?? 0;
    const headX = ax + Math.cos(yaw) * this.px(50);
    const headY = ay - Math.sin(yaw) * this.px(50);
    const angle = (-yaw * 180) / Math.PI;
    this.layer("arrow").innerHTML = `
      <rect x="${ax - radius}" y="${ay - radius}" width="${radius * 2}" height="${radius * 2}" fill="${MAP_COLORS.signal}" fill-opacity="0.08" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(2)}" stroke-dasharray="${this.px(6)} ${this.px(6)}"/>
      <path d="M${ax} ${ay} L${headX} ${headY}" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(4)}" stroke-linecap="round"/>
      <g transform="translate(${headX} ${headY}) rotate(${angle})"><path d="M${-this.px(10)} ${-this.px(10)} L0 0 L${-this.px(10)} ${this.px(10)}" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(4)}" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>
      <circle cx="${ax}" cy="${ay}" r="${this.px(13)}" fill="${MAP_COLORS.white}" stroke="${MAP_COLORS.signal}" stroke-width="${this.px(4)}" style="cursor:move"/>
      <circle cx="${hx}" cy="${hy}" r="${this.px(9)}" fill="${MAP_COLORS.signal}" stroke="${MAP_COLORS.white}" stroke-width="${this.px(3)}" style="cursor:grab"/>`;
  }
}

window.Concierge = Object.assign(window.Concierge ?? {}, { MapView });
