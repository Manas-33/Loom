const state = {
  jobs: [],
  filteredJobs: [],
  currentRunId: null,
  currentSource: null,
};

const elements = {
  tableBody: document.getElementById("jobs-table-body"),
  jobCount: document.getElementById("job-count"),
  jobFilter: document.getElementById("job-filter"),
  prepareForm: document.getElementById("prepare-form"),
  refreshButton: document.getElementById("refresh-button"),
  pipelineButton: document.getElementById("pipeline-button"),
  resumeMissingButton: document.getElementById("resume-missing-button"),
  coverMissingButton: document.getElementById("cover-missing-button"),
  compileButton: document.getElementById("compile-button"),
  docxButton: document.getElementById("docx-button"),
  diagnosticsGrid: document.getElementById("diagnostics-grid"),
  logOutput: document.getElementById("log-output"),
  runStatus: document.getElementById("run-status"),
  cancelButton: document.getElementById("cancel-button"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function artifactPill(label, enabled) {
  return `<span class="artifact-pill ${enabled ? "is-on" : "is-off"}">${escapeHtml(label)}</span>`;
}

function fileLink(slug, filename, label) {
  return `<a class="file-link" href="/api/files/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}">${escapeHtml(label)}</a>`;
}

function renderJobs() {
  const query = elements.jobFilter.value.trim().toLowerCase();
  state.filteredJobs = state.jobs.filter((job) => {
    const haystack = [job.slug, job.company, job.title, job.location, job.category]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });

  elements.jobCount.textContent = `${state.filteredJobs.length} jobs visible`;
  if (state.filteredJobs.length === 0) {
    elements.tableBody.innerHTML = `<tr><td colspan="4" class="empty-row">No jobs match this filter.</td></tr>`;
    return;
  }

  elements.tableBody.innerHTML = state.filteredJobs
    .map((job) => {
      const actions = `
        <div class="action-stack">
          <button class="mini-button" data-action="resume" data-slug="${job.slug}">Resume</button>
          <button class="mini-button" data-action="cover" data-slug="${job.slug}">Cover</button>
        </div>
      `;
      const downloads = [
        job.artifacts.resume_pdf ? fileLink(job.slug, "resume.pdf", "PDF") : "",
        job.artifacts.resume_tex ? fileLink(job.slug, "resume.tex", "TeX") : "",
        job.artifacts.cover_letter_docx ? fileLink(job.slug, "cover_letter.docx", "DOCX") : "",
        job.artifacts.cover_letter_json ? fileLink(job.slug, "cover_letter.json", "JSON") : "",
      ]
        .filter(Boolean)
        .join(" ");

      return `
        <tr>
          <td>
            <div class="job-main">
              <strong>${escapeHtml(job.title || job.slug)}</strong>
              <span>${escapeHtml(job.company || "Unknown company")}</span>
              <span>${escapeHtml(job.location || "Location not set")}</span>
              <code>${escapeHtml(job.slug)}</code>
            </div>
          </td>
          <td>
            <div class="artifact-grid">
              ${artifactPill("job", job.artifacts.job_md)}
              ${artifactPill("tex", job.artifacts.resume_tex)}
              ${artifactPill("pdf", job.artifacts.resume_pdf)}
              ${artifactPill("json", job.artifacts.cover_letter_json)}
              ${artifactPill("docx", job.artifacts.cover_letter_docx)}
            </div>
          </td>
          <td><div class="download-stack">${downloads || '<span class="muted">No files yet</span>'}</div></td>
          <td class="action-cell">${actions}</td>
        </tr>
      `;
    })
    .join("");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function loadJobs() {
  const data = await fetchJson("/api/jobs");
  state.jobs = data.jobs;
  renderJobs();
}

async function loadDiagnostics() {
  const data = await fetchJson("/api/diagnostics");
  const cards = [];

  Object.entries(data.commands).forEach(([name, value]) => {
    cards.push(`
      <article class="diag-card">
        <h3>${name}</h3>
        <p class="${value ? "ok" : "bad"}">${value || "Missing from PATH"}</p>
      </article>
    `);
  });

  Object.entries(data.packages).forEach(([name, value]) => {
    cards.push(`
      <article class="diag-card">
        <h3>${name}</h3>
        <p class="${value ? "ok" : "bad"}">${value ? "Installed" : "Missing"}</p>
      </article>
    `);
  });

  Object.entries(data.files).forEach(([name, value]) => {
    cards.push(`
      <article class="diag-card">
        <h3>${name}</h3>
        <p class="${value ? "ok" : "bad"}">${value ? "Present" : "Missing"}</p>
      </article>
    `);
  });

  elements.diagnosticsGrid.innerHTML = cards.join("");
}

function appendLog(line, label) {
  const prefix = label ? `[${label}] ` : "";
  if (elements.logOutput.textContent === "Waiting for a run…") {
    elements.logOutput.textContent = "";
  }
  elements.logOutput.textContent += `${prefix}${line}\n`;
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

function closeStream() {
  if (state.currentSource) {
    state.currentSource.close();
    state.currentSource = null;
  }
}

function trackRun(runId, streamUrl) {
  closeStream();
  state.currentRunId = runId;
  elements.cancelButton.disabled = false;
  elements.logOutput.textContent = "";
  elements.runStatus.textContent = "Connecting…";

  const source = new EventSource(streamUrl);
  state.currentSource = source;

  source.addEventListener("log", (event) => {
    const data = JSON.parse(event.data);
    appendLog(data.line, data.label);
  });

  source.addEventListener("status", async (event) => {
    const data = JSON.parse(event.data);
    elements.runStatus.textContent = data.status;
    if (["completed", "failed", "cancelled"].includes(data.status)) {
      elements.cancelButton.disabled = true;
      closeStream();
      await Promise.all([loadJobs(), loadDiagnostics()]);
    }
  });
}

async function startRun(url, body = {}) {
  const data = await fetchJson(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
  trackRun(data.run_id, data.stream_url);
}

elements.jobFilter.addEventListener("input", renderJobs);
elements.refreshButton.addEventListener("click", async () => {
  await Promise.all([loadJobs(), loadDiagnostics()]);
});

elements.pipelineButton.addEventListener("click", async () => {
  await startRun("/api/run/pipeline");
});

elements.prepareForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.target);
  const payload = {
    limit: formData.get("limit") ? Number(formData.get("limit")) : null,
    filter_company: formData.get("filter_company") || null,
    filter_category: formData.get("filter_category") || null,
    skip_existing: formData.get("skip_existing") === "on",
  };
  await startRun("/api/run/prepare", payload);
});

elements.resumeMissingButton.addEventListener("click", async () => {
  await startRun("/api/run/opencode-resume", { all_missing: true });
});

elements.coverMissingButton.addEventListener("click", async () => {
  await startRun("/api/run/opencode-cover", { all_missing: true });
});

elements.compileButton.addEventListener("click", async () => {
  await startRun("/api/run/compile-pdfs", { skip_existing: true });
});

elements.docxButton.addEventListener("click", async () => {
  await startRun("/api/run/build-cover-docx", { skip_existing: true });
});

elements.cancelButton.addEventListener("click", async () => {
  if (!state.currentRunId) {
    return;
  }
  await fetchJson(`/api/runs/${state.currentRunId}/cancel`, { method: "POST" });
});

elements.tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  const slug = button.dataset.slug;
  const action = button.dataset.action;
  const url = action === "resume" ? "/api/run/opencode-resume" : "/api/run/opencode-cover";
  await startRun(url, { slug });
});

Promise.all([loadJobs(), loadDiagnostics()]).catch((error) => {
  elements.runStatus.textContent = `Startup error: ${error.message}`;
});
