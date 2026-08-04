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
  return {
    running: false,
    nodes: nodeOrder.map((id) => ({ id, status: "pending", detail: "" })),
    log: [],
    start() {
      if (this.running) return;
      this.running = true;
      this.nodes.forEach((n) => { n.status = "pending"; n.detail = ""; });
      this.log = [];

      const source = new EventSource("/api/run");
      source.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        const node = this.nodes.find((n) => n.id === data.node);
        if (node) {
          node.status = "done";
          node.detail = data.detail;
        }
        this.log.unshift(`${data.label}: ${data.detail}`);
      };
      source.addEventListener("result", (evt) => {
        source.close();
        this.running = false;
        // Only reload on success - a failed run has nothing new to show,
        // and reloading would wipe the error line just added to this.log.
        if (JSON.parse(evt.data).ok) {
          window.location.reload();
        }
      });
      source.onerror = () => {
        source.close();
        this.running = false;
      };

      // Mark the first not-yet-done node as "running" once its predecessors finish.
      this._pulseInterval = setInterval(() => {
        let seenPending = false;
        for (const n of this.nodes) {
          if (n.status === "done") continue;
          if (!seenPending) { n.status = this.running ? "running" : n.status; seenPending = true; }
        }
        if (!this.running) clearInterval(this._pulseInterval);
      }, 200);
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
