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

  // Kept identical to the server-rendered markup in mission_control.html, so
  // the row added live after an upload and the row rendered on the next page
  // load say the same thing. A quiet tag rather than a sentence: the flag has
  // to stay - a row where nothing was extracted must not look like a fully
  // read one - but it does not need to shout on a dashboard.
  const LOW_CONFIDENCE_LABEL = "partial";
  const LOW_CONFIDENCE_TITLE =
    "Little could be read from this document - the extracted terms may be incomplete.";

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
    // Fall back to the filename, matching mission_control.html. A weak
    // extraction leaves vendor empty, and a row labelled only "U-0023" tells
    // the person who just uploaded a file nothing about which file it was.
    vendor.textContent = payload.vendor || payload.original_filename || "";
    const renewal = document.createElement("span");
    renewal.className = "upload-renewal";
    renewal.textContent = payload.renewal_date || "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-ghost btn-remove";
    remove.dataset.remove = payload.contract_id;
    remove.textContent = "Remove";
    li.append(link, vendor, renewal, remove);
    if (payload.low_confidence) {
      const warning = document.createElement("span");
      warning.className = "upload-partial";
      warning.textContent = LOW_CONFIDENCE_LABEL;
      warning.title = LOW_CONFIDENCE_TITLE;
      li.append(warning);
    }
    list.appendChild(li);
    wireRemove(remove);
  }

  // Extraction runs up to 3 agentic LLM iterations against a local model
  // (16-27s each, measured live), so a real upload takes 60-75s with no way
  // to know how far it has got - there is no "percent done" to report. This
  // starts an indeterminate progress bar plus a running elapsed-time counter
  // (built with createElement/textContent, never innerHTML - same rule as
  // the rest of this file) and returns a function that removes both. The
  // returned function is safe to call more than once and is called on every
  // exit from send(): success, an error response, and a network exception -
  // a failed upload must not leave a bar animating forever.
  function startProgress() {
    const wrap = document.createElement("div");
    wrap.className = "upload-progress";
    // The bar's motion and the elapsed text are cosmetic ticks, not the news
    // - the meaningful state changes (done, or what went wrong) are still
    // announced through #upload-status's own aria-live="polite". Without
    // this, a screen reader would re-announce the elapsed time every second
    // for up to 75 seconds.
    wrap.setAttribute("aria-live", "off");

    const track = document.createElement("div");
    track.className = "upload-progress-track";
    const fill = document.createElement("div");
    fill.className = "upload-progress-fill";
    track.appendChild(fill);

    const elapsed = document.createElement("span");
    elapsed.className = "upload-elapsed";
    elapsed.textContent = "0:00 elapsed";

    wrap.append(track, elapsed);
    status.insertAdjacentElement("afterend", wrap);

    const startedAt = performance.now();
    const tick = () => {
      const totalSeconds = Math.round((performance.now() - startedAt) / 1000);
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = String(totalSeconds % 60).padStart(2, "0");
      elapsed.textContent = `${minutes}:${seconds} elapsed`;
    };
    const timer = setInterval(tick, 1000);

    let stopped = false;
    return function stopProgress() {
      if (stopped) return;
      stopped = true;
      clearInterval(timer);
      wrap.remove();
    };
  }

  async function send(file) {
    // The 60-75s figure is measured live against the qwen3:1.7b model this
    // app runs locally, not a guess - see the extraction route's own comment
    // in main.py for the same number.
    status.textContent =
      `Reading ${file.name}… this usually takes about a minute (60–75s) ` +
      "with the local model.";
    status.className = "upload-status";
    const stopProgress = startProgress();
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/api/upload", { method: "POST", body });
      const payload = await response.json();
      stopProgress();
      if (!response.ok) {
        // The API's detail names the actual cause - show it rather than "upload failed".
        status.textContent = payload.detail || "Upload failed.";
        status.classList.add("is-error");
        return;
      }
      // Built with createElement/textContent, not innerHTML: payload.vendor is a
      // raw regex capture off the uploaded document's own text (see
      // extraction.py's VENDOR: search), completely unsanitized by the time it
      // reaches here. A file containing e.g. "VENDOR: <img src=x onerror=...>"
      // must render as inert text, never as markup the browser executes.
      status.textContent = "";
      status.append("Added ");
      const idEl = document.createElement("strong");
      idEl.textContent = payload.contract_id;
      status.append(idEl);
      if (payload.vendor) status.append(` - ${payload.vendor}`);
      status.append(". Re-run the analysis to include it.");
      // A file we could barely read is not an ordinary success. The row carries
      // the "partial" tag; here it is only a colour change, so the status line
      // stays one clean sentence.
      if (payload.low_confidence) {
        status.classList.add("is-warning");
      } else {
        status.classList.add("is-ok");
      }
      addRow(payload);
    } catch (err) {
      // Reached when fetch() itself rejects (e.g. the server dropped the
      // connection) or response.json() fails to parse - both happen before
      // the stopProgress() call above runs, so the bar and timer are still
      // up and must be torn down here too. stopProgress() is idempotent, so
      // this is safe even though it can never double-fire in practice: this
      // catch and the earlier stopProgress() cover disjoint failure points.
      stopProgress();
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
