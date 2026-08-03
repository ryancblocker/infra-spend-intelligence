// PACT frontend behavior: theme toggle, pipeline run SSE, count-up KPIs, ask-page chat.

(function () {
  const root = document.documentElement;
  const stored = localStorage.getItem("pact-theme");
  if (stored) root.setAttribute("data-theme", stored);

  window.pactToggleTheme = function () {
    const current = root.getAttribute("data-theme") === "light" ? "light" : "dark";
    const next = current === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    localStorage.setItem("pact-theme", next);
  };
})();

function countUp(el, target, opts) {
  opts = opts || {};
  const prefix = opts.prefix || "";
  const decimals = opts.decimals || 0;
  const duration = 900;
  const start = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const value = target * eased;
    el.textContent = prefix + value.toLocaleString(undefined, {
      minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-countup]").forEach((el) => {
    const target = parseFloat(el.getAttribute("data-countup"));
    if (Number.isFinite(target)) {
      countUp(el, target, { prefix: el.getAttribute("data-prefix") || "" });
    }
  });
});

// --- Pipeline run (Mission Control) ---

function pipelineRunner(completedDetails) {
  const nodeOrder = ["discovery", "extraction", "waste", "benchmark", "renewal", "optimization", "critic", "narrator"];

  // Render-pacing floor only. The offline pipeline completes in ~0.02s, which is
  // faster than a human can perceive, so state changes would land in a single
  // frame. This spaces out *rendering* - every status and detail string shown is
  // the real one reported by the backend. With a local model attached, actual
  // latency exceeds this floor and it has no effect at all.
  const MIN_DWELL_MS = 550;

  // Details from a previous completed run, so the pipeline renders finished on a
  // fresh page load rather than resetting every node to grey.
  const done = completedDetails || {};
  const hasPrevious = Object.keys(done).length > 0;

  return {
    running: false,
    nodes: nodeOrder.map((id) => ({
      id,
      status: hasPrevious ? "done" : "pending",
      detail: done[id] || "",
    })),
    log: [],
    _queue: [],
    _draining: false,
    _finished: false,
    _started: false,
    _source: null,
    complete: false,

    start() {
      if (this.running || this._started) return;
      this._started = true;
      this.running = true;
      this.nodes.forEach((n) => { n.status = "pending"; n.detail = ""; });
      this.log = [];
      this._queue = [];
      this._finished = false;

      // Drop ?start=1 from the address bar immediately. If it survives, any
      // reload - a manual refresh, a restored tab, a browser back - re-triggers
      // the autostart and the page runs the pipeline again in a loop.
      if (window.location.search) {
        window.history.replaceState({}, "", window.location.pathname);
      }

      const source = new EventSource("/api/run");
      this._source = source;

      source.onmessage = (evt) => {
        this._queue.push(JSON.parse(evt.data));
        this._drain();
      };
      source.addEventListener("result", () => {
        this._close();
        this._finished = true;
        this._drain();
      });
      // EventSource reconnects automatically whenever the stream ends - including
      // a clean end - which would kick off an entirely new pipeline run. Always
      // close it explicitly and never reopen.
      source.onerror = () => {
        this._close();
        if (!this._finished) this.running = false;
      };
    },

    _close() {
      if (this._source) {
        this._source.close();
        this._source = null;
      }
    },

    _drain() {
      if (this._draining) return;
      this._draining = true;
      const step = () => {
        const data = this._queue.shift();
        if (!data) {
          this._draining = false;
          if (this._finished) {
            this.running = false;
            this.complete = true;
            // Let the final node hold its green state for a beat, then load the
            // results. The reloaded page renders every node already complete
            // (details come from the server), so the pipeline stays green
            // instead of snapping back to grey.
            setTimeout(() => { window.location.href = "/"; }, 900);
          }
          return;
        }
        this._apply(data);
        setTimeout(step, MIN_DWELL_MS);
      };
      step();
    },

    _apply(data) {
      const node = this.nodes.find((n) => n.id === data.node);
      if (node) {
        if (data.status === "started") {
          node.status = "running";
        } else if (data.status === "error") {
          node.status = "error";
          node.detail = data.detail;
        } else {
          node.status = "done";
          node.detail = data.detail;
        }
      }
      // "started" carries no result yet, so it would only add noise to the feed.
      if (data.status !== "started") {
        this.log.unshift(`${data.label}: ${data.detail}`);
      }
    },
  };
}
window.pipelineRunner = pipelineRunner;

// --- Ask page ---

function askChat() {
  return {
    question: "",
    asking: false,
    messages: [],
    async send() {
      const q = this.question.trim();
      if (!q || this.asking) return;
      this.messages.push({ role: "user", text: q });
      this.question = "";
      this.asking = true;
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q }),
        });
        const data = await res.json();
        this.messages.push({ role: "assistant", text: data.answer, sources: data.sources, mode: data.mode });
      } catch (e) {
        this.messages.push({ role: "assistant", text: "Something went wrong reaching the ask endpoint.", sources: [] });
      } finally {
        this.asking = false;
        this.$nextTick(() => {
          const box = this.$refs.scrollbox;
          if (box) box.scrollTop = box.scrollHeight;
        });
      }
    },
  };
}
window.askChat = askChat;

// --- simple client-side table filter ---

// --- Contract upload ---------------------------------------------------------
(function () {
  const drop = document.getElementById("upload-drop");
  if (!drop) return;
  const input = document.getElementById("upload-input");
  const status = document.getElementById("upload-status");

  function wireRemove(button) {
    button.addEventListener("click", async () => {
      const id = button.dataset.remove;
      const response = await fetch(`/api/uploads/${id}/remove`, { method: "POST" });
      if (response.ok) {
        const row = button.closest("li");
        const list = row.parentElement;
        row.remove();
        if (list && !list.children.length) list.remove();
      }
    });
  }

  document.querySelectorAll("[data-remove]").forEach(wireRemove);

  document.getElementById("upload-browse").addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files[0]) send(input.files[0]);
    input.value = "";
  });

  ["dragover", "dragleave", "drop"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.toggle("is-over", name === "dragover");
      if (name === "drop" && event.dataTransfer.files[0]) send(event.dataTransfer.files[0]);
    });
  });

  function addRow(payload) {
    let list = document.getElementById("upload-list");
    if (!list) {
      const empty = document.getElementById("upload-list-empty");
      list = document.createElement("ul");
      list.id = "upload-list";
      list.className = "upload-list";
      if (empty) {
        empty.replaceWith(list);
      } else {
        status.insertAdjacentElement("afterend", list);
      }
    }
    const li = document.createElement("li");
    li.dataset.contractId = payload.contract_id;
    const link = document.createElement("a");
    link.href = `/contracts/${payload.contract_id}`;
    link.textContent = payload.contract_id;
    const vendor = document.createElement("span");
    vendor.className = "upload-vendor";
    vendor.textContent = payload.vendor || "";
    const renewal = document.createElement("span");
    renewal.className = "upload-renewal";
    renewal.textContent = payload.renewal_date || "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-ghost btn-remove";
    remove.dataset.remove = payload.contract_id;
    remove.textContent = "Remove";
    li.append(link, vendor, renewal, remove);
    list.appendChild(li);
    wireRemove(remove);
  }

  async function send(file) {
    status.textContent = `Reading ${file.name}...`;
    status.className = "upload-status";
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/api/upload", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) {
        // The API's detail names the actual cause - show it rather than "upload failed".
        status.textContent = payload.detail || "Upload failed.";
        status.classList.add("is-error");
        return;
      }
      status.innerHTML = `Added <strong>${payload.contract_id}</strong>` +
        `${payload.vendor ? ` - ${payload.vendor}` : ""}. ` +
        `Re-run the analysis to include it.`;
      status.classList.add("is-ok");
      addRow(payload);
    } catch (err) {
      status.textContent = `Upload failed: ${err.message}`;
      status.classList.add("is-error");
    }
  }
})();

function tableFilter() {
  return {
    query: "",
    filterRows(selector) {
      const q = this.query.toLowerCase();
      document.querySelectorAll(selector).forEach((row) => {
        const text = row.getAttribute("data-search") || row.textContent;
        row.style.display = text.toLowerCase().includes(q) ? "" : "none";
      });
    },
  };
}
window.tableFilter = tableFilter;
