class StatusBar {
  constructor(root = document) {
    this.fields = Object.fromEntries(
      [...root.querySelectorAll("[data-stat]")].map((node) => [node.dataset.stat, node]),
    );
  }

  start() {
    document.addEventListener("concierge:status", (event) => this.render(event.detail));
    document.addEventListener("concierge:socket", (event) => {
      if (!event.detail.connected) this.set("robot", "Console offline", "stop");
    });
  }

  set(key, text, tone) {
    const node = this.fields[key];
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("text-ok", tone === "ok");
    node.classList.toggle("text-caution", tone === "caution");
    node.classList.toggle("text-stop", tone === "stop");
  }

  render(status) {
    if (!status.connected) {
      this.set("robot", "Unreachable", "stop");
      return;
    }
    this.set("robot", "Connected", "ok");
    const power = status.power ?? {};
    const battery = power.batteryPercentage;
    this.set(
      "battery",
      typeof battery === "number" ? `${battery}%${power.isCharging ? ", charging" : ""}` : "–",
      typeof battery === "number" && battery < 20 ? "caution" : null,
    );
    this.set("dock", power.dockingStatus === "on_dock" ? "On dock" : "Not on dock");
    const [label, tone] = window.Concierge.localizationLabel(status.localization_state);
    const quality = typeof status.quality === "number" ? ` · ${status.quality}` : "";
    this.set("localization", `${label}${status.localization_state?.state === "localized" ? quality : ""}`, tone);
    const mapStatus = status.map_status ?? {};
    this.set(
      "map",
      status.mapping ? "Mapping" : status.map_name || (mapStatus.map_load_status === "LOADED" ? "Loaded" : mapStatus.map_load_status || "–"),
    );
    const arms = status.arms;
    if (arms) this.set("arms", arms.ready ? `${arms.motor_count}/14 ready` : "Not ready", arms.ready ? "ok" : "stop");
  }
}

class StopButton {
  constructor(button) {
    this.button = button;
  }

  start() {
    this.button?.addEventListener("click", async () => {
      this.button.disabled = true;
      try {
        const result = await window.Concierge.api.post("/api/concierge/stop");
        window.Concierge.toast.show(result.message, result.stopped ? "caution" : "neutral");
      } catch (error) {
        window.Concierge.toast.error(error, "Stop robot failed");
      } finally {
        this.button.disabled = false;
      }
    });
  }
}

/** Disable hardware buttons while another robot operation runs. */
class BusyGuard {

  render(snapshot) {
    const active = snapshot?.active;
    document.body.dataset.robotBusy = active ? "true" : "false";
    document.dispatchEvent(new CustomEvent("concierge:busy", { detail: { active } }));
  }

  start() {
    document.addEventListener("concierge:operations", (event) => this.render(event.detail.current));
    // Status changes (dock, localization, arms) also change what may be clicked.
    document.addEventListener("concierge:status", () =>
      document.dispatchEvent(new CustomEvent("concierge:busy", { detail: {} })),
    );
  }
}

window.Concierge.isBusy = () =>
  Boolean(window.Concierge.state.operations?.active) || Boolean(window.Concierge.state.pending);
window.Concierge.robotStatus = () => window.Concierge.state.status ?? {};

/**
 * Enable a button only when it can really act; otherwise grey it out and say why
 * (shown as the tooltip). Buttons that are mid-click stay locked.
 */
window.Concierge.gate = (button, reason) => {
  if (!button) return;
  if (button.dataset.pending === "true") {
    button.disabled = true;
    return;
  }
  button.disabled = Boolean(reason);
  button.title = reason || "";
};

/** First reason in a list of [blocked, reason] pairs, or null when all pass. */
window.Concierge.blocked = (...checks) => checks.find(([isBlocked]) => isBlocked)?.[1] ?? null;

/**
 * Run a click once: lock the button immediately, show progress, and unlock when
 * the request (and any operation it started) has finished.
 */
window.Concierge.act = (button, handler) => {
  button?.addEventListener("click", async (event) => {
    if (button.dataset.pending === "true" || button.disabled) return;
    const label = button.innerHTML;
    button.dataset.pending = "true";
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.innerHTML = `<span class="inline-block size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"></span>${button.textContent.trim()}…`;
    window.Concierge.state.pending = (window.Concierge.state.pending ?? 0) + 1;
    document.dispatchEvent(new CustomEvent("concierge:busy", { detail: {} }));
    try {
      await handler(event);
    } finally {
      window.Concierge.state.pending -= 1;
      button.dataset.pending = "false";
      button.removeAttribute("aria-busy");
      button.innerHTML = label;
      button.disabled = false;
      document.dispatchEvent(new CustomEvent("concierge:busy", { detail: {} }));
    }
  });
};

/** Replace innerHTML only when it changed, so a click is never lost to a re-render. */
window.Concierge.renderHtml = (node, html) => {
  if (node.dataset.renderedHtml === html) return false;
  node.dataset.renderedHtml = html;
  node.innerHTML = html;
  return true;
};

/** Human-readable preconditions shared by every page. */
window.Concierge.checks = () => {
  const status = window.Concierge.robotStatus();
  const power = status.power ?? {};
  const mapStatus = status.map_status ?? {};
  const busy = window.Concierge.isBusy();
  return {
    status,
    busy: [busy, "Wait for the running operation to finish"],
    offline: [!status.connected, "Tianyi is not reachable"],
    mapping: [Boolean(status.mapping), "Map building is active"],
    noMap: [mapStatus.map_load_status !== "LOADED", "No map is loaded"],
    notLocalized: [status.localization_enabled === false, "Localization is stopped"],
    lowQuality: [
      typeof status.quality !== "number" || status.quality < 50,
      `Localization quality is ${status.quality ?? "unknown"}; it needs at least 50`,
    ],
    offDock: [power.dockingStatus !== "on_dock", "Tianyi is not on the charging dock"],
    notCharging: [!power.isCharging, "Tianyi is not charging"],
    unbound: [!mapStatus.is_homedock_binded, "The charging dock is not bound"],
    moving: [Boolean(status.current_action), "Tianyi is moving"],
    armsNotReady: [status.arms && !status.arms.ready, `Arms are not ready: ${status.arms?.error ?? ""}`],
    unlocalized: [
      status.localization_state?.state !== "localized",
      `Tianyi is not localized: ${status.localization_state?.reason ?? "localize on Map & localization"}`,
    ],
  };
};

const LOCALIZATION_LABELS = {
  not_localized: ["Not localized", "stop"],
  localizing: ["Localizing…", "caution"],
  localized: ["Localized", "ok"],
  lost: ["Localization lost", "stop"],
};
window.Concierge.localizationLabel = (state) => LOCALIZATION_LABELS[state?.state] ?? ["Unknown", "caution"];

/** Show a hint element only while Tianyi is not localized. */
window.Concierge.bindLocalizationHint = (node) => {
  if (!node) return;
  document.addEventListener("concierge:status", (event) => {
    const state = event.detail.localization_state;
    node.hidden = !state || state.state === "localized";
    const text = node.querySelector("[data-localization-reason]");
    if (text && state) text.textContent = `${window.Concierge.localizationLabel(state)[0]}: ${state.reason ?? ""}`;
  });
};

document.addEventListener("DOMContentLoaded", () => {
  new StatusBar().start();
  new StopButton(document.querySelector("[data-stop-robot]")).start();
  new BusyGuard().start();
  window.Concierge.socket.start();
});
