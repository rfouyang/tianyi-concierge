class ConciergeApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

class ConciergeApi {
  static async request(method, path, body, { raw = false, headers = {} } = {}) {
    const options = { method, headers: { ...headers } };
    if (body !== undefined) {
      if (raw) {
        options.body = body;
      } else {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
    }
    const response = await fetch(path, options);
    if (response.status === 204) return null;
    let payload = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = { detail: text };
      }
    }
    if (!response.ok) {
      const detail = payload?.detail ?? payload?.message ?? `Request failed (${response.status})`;
      throw new ConciergeApiError(typeof detail === "string" ? detail : JSON.stringify(detail), response.status);
    }
    return payload;
  }

  static get(path) { return ConciergeApi.request("GET", path); }
  static post(path, body = {}) { return ConciergeApi.request("POST", path, body); }
  static put(path, body = {}) { return ConciergeApi.request("PUT", path, body); }
  static delete(path) { return ConciergeApi.request("DELETE", path); }
}

class Toast {
  static show(message, tone = "neutral", { timeout = 5000, title = "" } = {}) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const toneClass = {
      neutral: "border-line",
      ok: "border-[#b9d9bb]",
      stop: "border-[#e9b7b7]",
      caution: "border-[#f0cfa5]",
    }[tone] ?? "border-line";
    const item = document.createElement("div");
    item.className = `pointer-events-auto flex items-start gap-3 rounded-xl border ${toneClass} bg-card p-4 shadow-lg`;
    item.setAttribute("role", tone === "stop" ? "alert" : "status");
    item.innerHTML = `<div class="min-w-0 flex-1">${title ? `<p class="text-sm font-bold"></p>` : ""}<p class="text-[13px] leading-snug text-ink-2"></p></div>
      <button type="button" class="text-ink-3 hover:text-ink" aria-label="Dismiss">✕</button>`;
    if (title) item.querySelector("p.font-bold").textContent = title;
    item.querySelector("p.text-ink-2").textContent = message;
    item.querySelector("button").addEventListener("click", () => item.remove());
    host.appendChild(item);
    if (timeout) window.setTimeout(() => item.remove(), timeout);
  }

  static error(error, title = "") {
    Toast.show(error?.message ?? String(error), "stop", { timeout: 9000, title });
  }
}

const Fmt = {
  number(value, digits = 2) {
    return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "–";
  },
  pose(pose) {
    if (!pose || typeof pose.x !== "number") return "–";
    return `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}, ${Number(pose.yaw ?? 0).toFixed(2)}`;
  },
  degrees(radians) {
    const degrees = ((radians * 180) / Math.PI) % 360;
    return `${Math.round(degrees < 0 ? degrees + 360 : degrees)}°`;
  },
  escape(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  },
  poiName(poi) {
    return poi?.metadata?.display_name || "Unnamed";
  },
  time(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  },
};

/** Bind a checkbox so that a set of buttons stays disabled until it is checked. */
function requireConfirmation(checkbox, buttons, isAllowed = () => true) {
  const sync = () => {
    for (const button of buttons) button.disabled = !checkbox.checked || !isAllowed();
  };
  checkbox.addEventListener("change", sync);
  sync();
  return sync;
}

window.Concierge = Object.assign(window.Concierge ?? {}, {
  api: ConciergeApi,
  toast: Toast,
  fmt: Fmt,
  requireConfirmation,
  state: { status: null, operations: null },
});
