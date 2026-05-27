/**
 * app.js — pipelinedoc frontend
 *
 * Calls POST /triage on the backend and consumes the streaming NDJSON
 * response line-by-line using fetch() + ReadableStream + TextDecoder.
 *
 * Each NDJSON line: { "step": string, "content": string, "status": "running"|"done"|"error" }
 *
 * Update API_BASE_URL to your Hugging Face Space URL before deploying to Firebase Hosting.
 */

// ── Config ──────────────────────────────────────────────────────────────────

const API_BASE_URL = "https://mew228-pipelinedoc.hf.space";

// ── Step display metadata ────────────────────────────────────────────────────
// Use Object.create(null) to prevent prototype-pollution via server-controlled keys.

const STEP_META = Object.assign(Object.create(null), {
  detect_pipeline: { label: "DETECT",   icon: "🔍" },
  list_jobs:       { label: "JOBS",     icon: "📋" },
  read_logs:       { label: "LOGS",     icon: "📄" },
  trace_commit:    { label: "COMMIT",   icon: "🔗" },
  gemini_analysis: { label: "GEMINI",   icon: "🧠" },
  create_issue:    { label: "ISSUE",    icon: "🐛" },
  comment_mr:      { label: "MR NOTE",  icon: "💬" },
  triage_complete: { label: "DONE",     icon: "✅" },
});

// Allow-listed status values; anything else falls back to a plain span.
const ALLOWED_STATUSES = new Set(["running", "done", "error"]);

// ── State ────────────────────────────────────────────────────────────────────

let isRunning = false;

// ── Status badge ─────────────────────────────────────────────────────────────

function setStatusBadge(state) {
  const badge = document.getElementById("status-badge");
  if (!badge) return;
  const STATES = { idle: "IDLE", running: "RUNNING", done: "DONE", error: "ERROR" };
  badge.textContent = STATES[state] ?? "IDLE";
  badge.className = "terminal-status-badge" + (state !== "idle" ? " " + state : "");
}

// Map from step ID → DOM element (null-prototype to prevent prototype pollution)
const stepElements = Object.create(null);

// ── DOM helpers ──────────────────────────────────────────────────────────────

function getOutput() {
  return document.getElementById("terminal-output");
}

function scrollBottom() {
  const el = getOutput();
  el.scrollTop = el.scrollHeight;
}

/**
 * appendLine — creates a <div> with textContent (never innerHTML).
 * cls must only be callee-controlled strings (not user input).
 */
function appendLine(text, cls = "") {
  const div = document.createElement("div");
  div.className = "terminal-line" + (cls ? " " + cls : "");
  div.textContent = text;
  getOutput().appendChild(div);
  scrollBottom();
}

function appendSep() {
  const div = document.createElement("div");
  div.className = "sep-line";
  div.textContent = "──────────────────────────────────────────────────────";
  getOutput().appendChild(div);
  scrollBottom();
}

/** Build a badge <span> for severity levels found in Gemini output. */
function severityBadge(line) {
  const m = line.match(/\[(CRITICAL|HIGH|MEDIUM|LOW)\]/i);
  if (!m) {
    const span = document.createElement("span");
    span.textContent = line;
    return span;
  }
  const sev = m[1].toLowerCase(); // always one of four safe literals
  const frag = document.createDocumentFragment();
  const parts = line.split(m[0]); // at most 2 parts
  frag.appendChild(document.createTextNode(parts[0]));
  const badge = document.createElement("span");
  badge.className = "badge badge-" + sev;
  badge.textContent = m[0];
  frag.appendChild(badge);
  if (parts[1]) frag.appendChild(document.createTextNode(parts[1]));
  return frag;
}

// ── Step renderer ────────────────────────────────────────────────────────────

/**
 * Build the status icon element using the DOM — never innerHTML.
 * status is validated against the allow-list before use.
 */
function buildIconEl(safeStatus) {
  const span = document.createElement("span");
  if (safeStatus === "running") {
    span.className = "step-icon running spinner";
  } else if (safeStatus === "done") {
    span.className = "step-icon done";
    span.textContent = "✓";
  } else if (safeStatus === "error") {
    span.className = "step-icon error";
    span.textContent = "✗";
  } else {
    span.className = "step-icon";
    span.textContent = "▸";
  }
  return span;
}

/** Build or update a step <div> entirely via DOM APIs. */
function renderStep(step, content, status) {
  // Sanitise server-controlled keys against allow-lists
  const safeMeta = Object.prototype.hasOwnProperty.call(STEP_META, step)
    ? STEP_META[step]
    : { label: step.toUpperCase().slice(0, 32), icon: "▸" };

  const safeStatus = ALLOWED_STATUSES.has(status) ? status : "running";

  // Build content node — split on newlines; apply badge only for gemini step.
  function buildContentNode() {
    const wrapper = document.createDocumentFragment();
    const lines = content.split("\n");
    lines.forEach((line, i) => {
      if (step === "gemini_analysis") {
        wrapper.appendChild(severityBadge(line));
      } else {
        wrapper.appendChild(document.createTextNode(line));
      }
      if (i < lines.length - 1) wrapper.appendChild(document.createElement("br"));
    });
    return wrapper;
  }

  // If this step already has a DOM element, update it in-place.
  const existing = Object.prototype.hasOwnProperty.call(stepElements, step)
    ? stepElements[step]
    : null;

  if (existing && existing.isConnected) {
    existing.className = "step-line status-" + safeStatus;

    const labelDiv = existing.querySelector(".step-label");
    const contentDiv = existing.querySelector(".step-content");

    // Replace icon
    const oldIcon = labelDiv.querySelector(".step-icon");
    labelDiv.replaceChild(buildIconEl(safeStatus), oldIcon);

    // Replace content
    contentDiv.className = "step-content status-" + safeStatus;
    contentDiv.textContent = "";
    contentDiv.appendChild(buildContentNode());

    scrollBottom();
    return;
  }

  // First occurrence — create the full element.
  const wrapper = document.createElement("div");
  wrapper.className = "step-line status-" + safeStatus;

  const labelDiv = document.createElement("div");
  labelDiv.className = "step-label";
  labelDiv.appendChild(buildIconEl(safeStatus));

  const nameSpan = document.createElement("span");
  nameSpan.className = "step-name";
  nameSpan.textContent = safeMeta.label;
  labelDiv.appendChild(nameSpan);

  const contentDiv = document.createElement("div");
  contentDiv.className = "step-content status-" + safeStatus;
  contentDiv.appendChild(buildContentNode());

  wrapper.appendChild(labelDiv);
  wrapper.appendChild(contentDiv);

  stepElements[step] = wrapper;
  getOutput().appendChild(wrapper);
  scrollBottom();
}

// ── Main triage runner ───────────────────────────────────────────────────────

async function runTriage() {
  if (isRunning) return;

  const projectId = document.getElementById("project-id").value.trim();
  const branch    = document.getElementById("branch-name").value.trim() || "main";

  if (!projectId) {
    document.getElementById("project-id").focus();
    return;
  }

  // Reset step tracking
  for (const k of Object.keys(stepElements)) delete stepElements[k];

  // Update UI state
  isRunning = true;
  setStatusBadge("running");
  const btn = document.getElementById("run-btn");
  btn.disabled = true;
  document.getElementById("btn-text").textContent = "Running…";

  // Clear old output and print header using DOM APIs
  const out = getOutput();
  out.textContent = "";

  const header = document.createElement("div");
  header.className = "welcome-line";
  const acc = document.createElement("span");
  acc.className = "acc";
  acc.textContent = "$";
  header.appendChild(acc);
  header.appendChild(document.createTextNode(
    ` pipelinedoc triage --project "${projectId}" --branch "${branch}"`
  ));
  out.appendChild(header);
  appendSep();

  try {
    const response = await fetch(`${API_BASE_URL}/triage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, branch }),
    });

    if (!response.ok) {
      const errText = await response.text();
      appendLine(`HTTP ${response.status}: ${errText}`, "step-content status-error");
      return;
    }

    // Consume the ReadableStream line by line
    const reader  = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let   buffer  = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on newlines — each NDJSON line is one step
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete trailing line in buffer

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        let parsed;
        try {
          parsed = JSON.parse(trimmed);
        } catch {
          appendLine(`[parse error] ${trimmed}`, "step-content status-error");
          continue;
        }

        renderStep(
          typeof parsed.step    === "string" ? parsed.step    : "",
          typeof parsed.content === "string" ? parsed.content : "",
          typeof parsed.status  === "string" ? parsed.status  : "running"
        );
      }
    }

    // Handle any remaining buffer content
    if (buffer.trim()) {
      try {
        const parsed = JSON.parse(buffer.trim());
        renderStep(
          typeof parsed.step    === "string" ? parsed.step    : "",
          typeof parsed.content === "string" ? parsed.content : "",
          typeof parsed.status  === "string" ? parsed.status  : "running"
        );
      } catch {
        // Ignore incomplete final line
      }
    }

    setStatusBadge("done");

  } catch (err) {
    setStatusBadge("error");
    appendSep();
    appendLine(`Connection error: ${err.message}`, "step-content status-error");
    appendLine("Is the backend running? Check API_BASE_URL in app.js.", "welcome-line dim");
  } finally {
    appendSep();
    const cursor = document.createElement("div");
    cursor.className = "welcome-line dim";
    cursor.textContent = "$ _";
    getOutput().appendChild(cursor);

    isRunning = false;
    btn.disabled = false;
    document.getElementById("btn-text").textContent = "Run Triage";
    scrollBottom();
  }
}

// ── Clear output ─────────────────────────────────────────────────────────────

function clearOutput() {
  if (isRunning) return;
  for (const k of Object.keys(stepElements)) delete stepElements[k];

  const out = getOutput();
  out.textContent = "";

  const line1 = document.createElement("div");
  line1.className = "welcome-line";
  const acc = document.createElement("span");
  acc.className = "acc";
  acc.textContent = "pipelinedoc";
  line1.appendChild(acc);
  line1.appendChild(document.createTextNode(" ready. Enter a GitLab project and run triage."));
  out.appendChild(line1);

  const line2 = document.createElement("div");
  line2.className = "welcome-line dim";
  line2.textContent = "All GitLab data is fetched via MCP · Analysis by Gemini 2.0 Flash";
  out.appendChild(line2);
}

// ── Keyboard shortcut: Enter in inputs ──────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  ["project-id", "branch-name"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => {
      if (e.key === "Enter") runTriage();
    });
  });
});
