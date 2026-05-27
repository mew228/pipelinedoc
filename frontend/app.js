/**
 * app.js — pipelinedoc frontend
 *
 * Calls POST /triage on the backend and consumes the streaming NDJSON
 * response line-by-line using fetch() + ReadableStream + TextDecoder.
 *
 * Each NDJSON line: { "step": string, "content": string, "status": "running"|"done"|"error" }
 *
 * Update API_BASE_URL to your Cloud Run URL before deploying to Firebase Hosting.
 */

// ── Config ──────────────────────────────────────────────────────────────────

const API_BASE_URL = "https://mew228-pipelinedoc.hf.space"; // ← Replace with Cloud Run URL after deploy

// ── Step display metadata ────────────────────────────────────────────────────

const STEP_META = {
  detect_pipeline: { label: "DETECT",   icon: "🔍" },
  list_jobs:       { label: "JOBS",     icon: "📋" },
  read_logs:       { label: "LOGS",     icon: "📄" },
  trace_commit:    { label: "COMMIT",   icon: "🔗" },
  gemini_analysis: { label: "GEMINI",   icon: "🧠" },
  create_issue:    { label: "ISSUE",    icon: "🐛" },
  comment_mr:      { label: "MR NOTE",  icon: "💬" },
  triage_complete: { label: "DONE",     icon: "✅" },
};

// ── State ────────────────────────────────────────────────────────────────────

let isRunning = false;

// ── DOM helpers ──────────────────────────────────────────────────────────────

function getOutput() {
  return document.getElementById("terminal-output");
}

function scrollBottom() {
  const el = getOutput();
  el.scrollTop = el.scrollHeight;
}

function appendRaw(html) {
  const el = getOutput();
  el.insertAdjacentHTML("beforeend", html);
  scrollBottom();
}

function appendSep() {
  appendRaw(`<div class="sep-line">──────────────────────────────────────────────────────</div>`);
}

function appendLine(text, cls = "") {
  const safe = escapeHtml(text);
  appendRaw(`<div class="terminal-line ${cls}">${safe}</div>`);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function severityBadge(content) {
  const m = content.match(/\[(CRITICAL|HIGH|MEDIUM|LOW)\]/i);
  if (!m) return escapeHtml(content);
  const sev = m[1].toLowerCase();
  return escapeHtml(content).replace(
    `[${m[1]}]`,
    `<span class="badge badge-${sev}">[${m[1]}]</span>`
  );
}

// ── Step renderer ────────────────────────────────────────────────────────────

/** Map from step ID → DOM element ID for in-place update of running steps */
const stepElementIds = {};

function renderStep(step, content, status) {
  const meta = STEP_META[step] || { label: step.toUpperCase(), icon: "▸" };

  const iconMap = {
    running: `<span class="step-icon running spinner"></span>`,
    done:    `<span class="step-icon done">✓</span>`,
    error:   `<span class="step-icon error">✗</span>`,
  };
  const icon = iconMap[status] || `<span class="step-icon">▸</span>`;

  // Format content lines with newline support
  const contentHtml = content
    .split("\n")
    .map((l) => (step === "gemini_analysis" ? severityBadge(l) : escapeHtml(l)))
    .join("<br/>");

  // If this step already has a DOM element, update it in place
  const existingId = stepElementIds[step];
  if (existingId) {
    const el = document.getElementById(existingId);
    if (el) {
      el.className = `step-line status-${status}`;
      el.innerHTML = `
        <div class="step-label">
          ${icon}
          <span class="step-name">${escapeHtml(meta.label)}</span>
        </div>
        <div class="step-content status-${status}">${contentHtml}</div>
      `;
      scrollBottom();
      return;
    }
  }

  // First time we see this step — create a new element
  const elemId = `step-${step}-${Date.now()}`;
  stepElementIds[step] = elemId;

  const html = `
    <div id="${elemId}" class="step-line status-${status}">
      <div class="step-label">
        ${icon}
        <span class="step-name">${escapeHtml(meta.label)}</span>
      </div>
      <div class="step-content status-${status}">${contentHtml}</div>
    </div>
  `;
  appendRaw(html);
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
  Object.keys(stepElementIds).forEach((k) => delete stepElementIds[k]);

  // Update UI state
  isRunning = true;
  const btn = document.getElementById("run-btn");
  btn.disabled = true;
  document.getElementById("btn-text").textContent = "[ RUNNING... ]";

  // Clear old output and print header
  getOutput().innerHTML = "";
  appendRaw(`<div class="welcome-line"><span class="acc">$</span> pipelinedoc triage --project "${escapeHtml(projectId)}" --branch "${escapeHtml(branch)}"</div>`);
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

        renderStep(parsed.step, parsed.content, parsed.status);
      }
    }

    // Handle any remaining buffer content
    if (buffer.trim()) {
      try {
        const parsed = JSON.parse(buffer.trim());
        renderStep(parsed.step, parsed.content, parsed.status);
      } catch {
        // Ignore incomplete final line
      }
    }

  } catch (err) {
    appendSep();
    appendLine(`Connection error: ${err.message}`, "step-content status-error");
    appendLine("Is the backend running? Check API_BASE_URL in app.js.", "welcome-line dim");
  } finally {
    appendSep();
    appendRaw(`<div class="welcome-line dim">$ _</div>`);
    isRunning = false;
    btn.disabled = false;
    document.getElementById("btn-text").textContent = "[ RUN TRIAGE ]";
    scrollBottom();
  }
}

// ── Clear output ─────────────────────────────────────────────────────────────

function clearOutput() {
  if (isRunning) return;
  Object.keys(stepElementIds).forEach((k) => delete stepElementIds[k]);
  getOutput().innerHTML = `
    <div class="welcome-line">
      <span class="acc">pipelinedoc</span> ready. Enter a GitLab project and run triage.
    </div>
    <div class="welcome-line dim">
      All GitLab data is fetched via MCP · Analysis by Gemini 2.0 Flash
    </div>
  `;
}

// ── Keyboard shortcut: Enter in inputs ──────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  ["project-id", "branch-name"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => {
      if (e.key === "Enter") runTriage();
    });
  });
});
