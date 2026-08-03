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

function pipelineRunner() {
  const nodeOrder = ["discovery", "extraction", "waste", "benchmark", "renewal", "optimization", "critic", "narrator"];

  // Render-pacing floor only. The offline pipeline completes in ~0.02s, which is
  // faster than a human can perceive, so state changes would land in a single
  // frame. This spaces out *rendering* - every status and detail string shown is
  // the real one reported by the backend. With a local model attached, actual
  // latency exceeds this floor and it has no effect at all.
  const MIN_DWELL_MS = 400;

  return {
    running: false,
    nodes: nodeOrder.map((id) => ({ id, status: "pending", detail: "" })),
    log: [],
    _queue: [],
    _draining: false,
    _finished: false,

    start() {
      if (this.running) return;
      this.running = true;
      this.nodes.forEach((n) => { n.status = "pending"; n.detail = ""; });
      this.log = [];
      this._queue = [];
      this._finished = false;

      const source = new EventSource("/api/run");
      source.onmessage = (evt) => {
        this._queue.push(JSON.parse(evt.data));
        this._drain();
      };
      source.addEventListener("result", () => {
        source.close();
        this._finished = true;
        this._drain();
      });
      source.onerror = () => {
        source.close();
        this.running = false;
      };
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
            // Navigate rather than reload: reloading would preserve ?start=1
            // and immediately kick off another run.
            window.location.href = "/";
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
