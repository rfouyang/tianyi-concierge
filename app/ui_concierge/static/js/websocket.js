/**
 * One WebSocket per page. Status and operation snapshots are re-broadcast as
 * DOM events so every panel reads the same state without polling the robot.
 */
class ConciergeSocket {
  constructor() {
    this.socket = null;
    this.reconnectTimer = null;
    this.connected = false;
  }

  start() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${window.location.host}/api/concierge/ws`);
    this.socket.addEventListener("open", () => this.setConnected(true));
    this.socket.addEventListener("message", (event) => this.receive(event));
    this.socket.addEventListener("close", () => {
      this.setConnected(false);
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = window.setTimeout(() => this.start(), 1500);
    });
  }

  setConnected(connected) {
    this.connected = connected;
    document.dispatchEvent(new CustomEvent("concierge:socket", { detail: { connected } }));
  }

  receive(event) {
    const message = JSON.parse(event.data);
    if (message.type === "status") {
      window.Concierge.state.status = message;
      document.dispatchEvent(new CustomEvent("concierge:status", { detail: message }));
    } else if (message.type === "operations") {
      const previous = window.Concierge.state.operations;
      window.Concierge.state.operations = message;
      document.dispatchEvent(new CustomEvent("concierge:operations", { detail: { current: message, previous } }));
    } else if (message.type === "mrt") {
      window.Concierge.state.mrtActive = message.active_operation_id;
      document.dispatchEvent(new CustomEvent("concierge:mrt", { detail: message }));
    }
  }
}

/** Resolve when the operation with ``id`` finishes; reject if it fails. */
function waitForOperation(id) {
  return new Promise((resolve, reject) => {
    const check = (snapshot) => {
      if (!snapshot) return false;
      const latest = snapshot.latest;
      if (snapshot.active?.id === id) return false;
      if (latest?.id === id) {
        document.removeEventListener("concierge:operations", listener);
        if (latest.status === "failed") reject(new Error(latest.error || latest.message));
        else resolve(latest);
        return true;
      }
      return false;
    };
    const listener = (event) => check(event.detail.current);
    document.addEventListener("concierge:operations", listener);
    check(window.Concierge.state.operations);
  });
}

/** Start an operation endpoint, report its outcome, and return the result. */
async function runOperation(path, body, { success, failureTitle } = {}) {
  const { api, toast } = window.Concierge;
  const operation = await api.post(path, body);
  try {
    const finished = await waitForOperation(operation.id);
    if (success) toast.show(typeof success === "function" ? success(finished) : success, "ok");
    return finished;
  } catch (error) {
    toast.error(error, failureTitle || `${operation.label} failed`);
    throw error;
  }
}

window.Concierge = Object.assign(window.Concierge ?? {}, {
  socket: new ConciergeSocket(),
  waitForOperation,
  runOperation,
});
