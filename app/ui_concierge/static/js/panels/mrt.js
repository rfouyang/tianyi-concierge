const MRT_TERMINAL = new Set(["completed", "cancelled", "failed"]);

class MrtPanel {
  constructor(root = document) {
    const q = (selector) => root.querySelector(selector);
    this.confirm = q("[data-mrt-confirm]");
    this.runButtons = [...root.querySelectorAll("[data-mrt-run]")];
    this.labels = Object.fromEntries(this.runButtons.map((b) => [b.dataset.mrtRun, b.textContent.trim()]));
    this.cards = Object.fromEntries([...root.querySelectorAll("[data-mrt-card]")].map((n) => [n.dataset.mrtCard, n]));
    this.cancelButton = q("[data-mrt-cancel]");
    this.refreshButton = q("[data-mrt-refresh]");
    this.healthDot = q("[data-mrt-health-dot]");
    this.healthText = q("[data-mrt-health-text]");
    this.opSub = q("[data-mrt-op-sub]");
    this.opStatus = q("[data-mrt-op-status]");
    this.opMessage = q("[data-mrt-op-message]");
    this.health = null;
    this.operation = null;
  }

  start() {
    this.confirm.addEventListener("change", () => this.render());
    this.refreshButton.addEventListener("click", () => this.refresh());
    this.cancelButton.addEventListener("click", () => this.cancel());
    for (const button of this.runButtons) button.addEventListener("click", () => this.run(button.dataset.mrtRun));
    this.refresh();
    window.setInterval(() => this.poll(), 500);
  }

  async refresh() {
    try {
      this.health = await window.Concierge.api.get("/ui/mrt/health");
      this.operation = this.health.active_operation ?? this.health.latest_operation ?? this.operation;
    } catch (error) {
      this.health = { ready: false, error: error.message };
    }
    this.render();
  }

  async poll() {
    const active = this.operation && !MRT_TERMINAL.has(this.operation.status);
    if (active) {
      try {
        this.operation = await window.Concierge.api.get(`/ui/mrt/interventions/${this.operation.operation_id}`);
      } catch {
        /* keep the last known state */
      }
      this.render();
    } else if (!this.lastHealth || Date.now() - this.lastHealth > 5000) {
      this.lastHealth = Date.now();
      this.refresh();
    }
  }

  render() {
    const ready = Boolean(this.health?.ready);
    this.healthDot.className = `size-2.5 rounded-full ${ready ? "bg-ok" : "bg-stop"}`;
    this.healthText.textContent = ready
      ? `Ready. ${this.health.motor_count} arm motors detected.`
      : `Not ready: ${this.health?.error || "health check failed"}`;
    const op = this.operation;
    const active = op && !MRT_TERMINAL.has(op.status);
    for (const button of this.runButtons) {
      const id = button.dataset.mrtRun;
      const running = active && op.action_id === id;
      button.disabled = this.pending || !ready || active || !this.confirm.checked;
      button.title = !ready ? "The MRT service is not ready" : active ? "An intervention is running" : !this.confirm.checked ? "Confirm the arm areas are clear first" : "";
      button.textContent = running ? "Running…" : this.labels[id];
      this.cards[id].classList.toggle("border-signal", Boolean(running));
      this.cards[id].classList.toggle("border-2", Boolean(running));
    }
    this.cancelButton.disabled = this.pending || !active;
    if (op) {
      const label = this.cards[op.action_id]?.querySelector("h2").textContent ?? op.action_id;
      this.opSub.textContent = `${label} · ${op.request_id}`;
      this.opStatus.hidden = false;
      this.opStatus.textContent = op.status.replaceAll("_", " ");
      this.opStatus.className = `badge ${active ? "badge-signal badge-dot" : op.status === "completed" ? "badge-ok" : op.status === "failed" ? "badge-stop" : "badge-neutral"}`;
      this.opMessage.textContent = op.error ? `${op.message}: ${op.error}` : op.message;
    }
  }

  async run(actionId) {
    if (this.pending) return;
    this.pending = true;
    this.render();
    try {
      this.operation = await window.Concierge.api.post("/ui/mrt/interventions", {
        action_id: actionId,
        arm_motion_confirmed: this.confirm.checked,
      });
      this.confirm.checked = false;
    } catch (error) {
      window.Concierge.toast.error(error, "Could not start the intervention");
    } finally {
      this.pending = false;
    }
    this.render();
  }

  async cancel() {
    if (this.pending) return;
    this.pending = true;
    this.cancelButton.disabled = true;
    try {
      this.operation = await window.Concierge.api.post(`/ui/mrt/interventions/${this.operation.operation_id}/cancel`);
    } catch (error) {
      window.Concierge.toast.error(error, "Cancel failed");
    } finally {
      this.pending = false;
    }
    this.render();
  }
}

document.addEventListener("DOMContentLoaded", () => new MrtPanel().start());
