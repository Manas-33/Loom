const state = {
  jobs: [],
  filteredJobs: [],
  currentPageJobs: [],
  currentPage: 1,
  pageSize: 10,
  theme: "light",
  currentRunId: null,
  currentSource: null,
};

const elements = {
  tableBody: document.getElementById("jobs-table-body"),
  jobCount: document.getElementById("job-count"),
  jobFilter: document.getElementById("job-filter"),
  paginationSummary: document.getElementById("pagination-summary"),
  paginationPage: document.getElementById("pagination-page"),
  paginationPrev: document.getElementById("pagination-prev"),
  paginationNext: document.getElementById("pagination-next"),
  prepareForm: document.getElementById("prepare-form"),
  refreshButton: document.getElementById("refresh-button"),
  pipelineButton: document.getElementById("pipeline-button"),
  themeToggle: document.getElementById("theme-toggle"),
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
  return `<a class="file-link" href="/view/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function statusControls(job) {
  const tone = String(job.status).toLowerCase().replaceAll(" ", "-");
  const options = (job.available_statuses || ["Not Applied", "Applied", "Reject", "Ignore"])
    .map(
      (status) =>
        `<option value="${escapeHtml(status)}"${job.status === status ? " selected" : ""}>${escapeHtml(status)}</option>`,
    )
    .join("");
  return `
    <div class="status-stack">
      <span class="status-pill status-${tone}">${escapeHtml(job.status)}</span>
      <label class="status-field">
        <select class="status-select" data-status-slug="${escapeHtml(job.slug)}" aria-label="Status for ${escapeHtml(job.slug)}">
          ${options}
        </select>
      </label>
    </div>
  `;
}

function statusCellClass(status) {
  return `status-cell status-cell-${String(status).toLowerCase().replaceAll(" ", "-")}`;
}

function statusRowClass(status) {
  return `job-row job-row-${String(status).toLowerCase().replaceAll(" ", "-")}`;
}

function clampPage(page, totalPages) {
  return Math.min(Math.max(page, 1), Math.max(totalPages, 1));
}

function applyTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  elements.themeToggle.setAttribute(
    "aria-label",
    state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode",
  );
  elements.themeToggle.setAttribute(
    "title",
    state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode",
  );
  window.localStorage.setItem("loom-theme", state.theme);
}

function initializeTheme() {
  const savedTheme = window.localStorage.getItem("loom-theme");
  if (savedTheme) {
    applyTheme(savedTheme);
    return;
  }

  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(prefersDark ? "dark" : "light");
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
  const totalPages = Math.max(Math.ceil(state.filteredJobs.length / state.pageSize), 1);
  state.currentPage = clampPage(state.currentPage, totalPages);

  if (state.filteredJobs.length === 0) {
    state.currentPageJobs = [];
    elements.tableBody.innerHTML = `<tr><td colspan="6" class="empty-row">No jobs match this filter.</td></tr>`;
    elements.paginationSummary.textContent = "Showing 0-0 of 0 jobs";
    elements.paginationPage.textContent = "Page 1 of 1";
    elements.paginationPrev.disabled = true;
    elements.paginationNext.disabled = true;
    return;
  }

  const startIndex = (state.currentPage - 1) * state.pageSize;
  const endIndex = startIndex + state.pageSize;
  state.currentPageJobs = state.filteredJobs.slice(startIndex, endIndex);

  elements.paginationSummary.textContent = `Showing ${startIndex + 1}-${Math.min(endIndex, state.filteredJobs.length)} of ${state.filteredJobs.length} jobs`;
  elements.paginationPage.textContent = `Page ${state.currentPage} of ${totalPages}`;
  elements.paginationPrev.disabled = state.currentPage === 1;
  elements.paginationNext.disabled = state.currentPage === totalPages;

  elements.tableBody.innerHTML = state.currentPageJobs
    .map((job, index) => {
      const actions = `
        <div class="action-stack">
          <button class="mini-button" data-action="resume" data-slug="${job.slug}">Resume</button>
          <button class="mini-button" data-action="cover" data-slug="${job.slug}">Cover</button>
        </div>
      `;
      const downloads = [
        job.artifacts.resume_pdf ? fileLink(job.slug, "resume.pdf", "View PDF") : "",
        job.artifacts.resume_tex ? fileLink(job.slug, "resume.tex", "View TeX") : "",
        job.artifacts.cover_letter_docx ? fileLink(job.slug, "cover_letter.docx", "Open DOCX") : "",
        job.artifacts.cover_letter_json ? fileLink(job.slug, "cover_letter.json", "View JSON") : "",
      ]
        .filter(Boolean)
        .join(" ");

      return `
        <tr class="${statusRowClass(job.status)}">
          <td class="serial-cell">${startIndex + index + 1}</td>
          <td class="job-cell">
            <div class="job-main">
              <div style="display: flex; align-items: center; gap: 8px;">
                <strong>${escapeHtml(job.title || job.slug)}</strong>
                ${job.url ? `<a href="${escapeHtml(job.url)}" target="_blank" class="mini-button" style="text-decoration: none; padding: 2px 8px; font-size: 0.75rem; min-width: auto; min-height: auto;">Link ↗</a>` : ''}
              </div>
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
          <td class="${statusCellClass(job.status)}">${statusControls(job)}</td>
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

elements.jobFilter.addEventListener("input", () => {
  state.currentPage = 1;
  renderJobs();
});
elements.paginationPrev.addEventListener("click", () => {
  state.currentPage -= 1;
  renderJobs();
});
elements.paginationNext.addEventListener("click", () => {
  state.currentPage += 1;
  renderJobs();
});
elements.themeToggle.addEventListener("click", () => {
  applyTheme(state.theme === "dark" ? "light" : "dark");
});
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

elements.tableBody.addEventListener("change", async (event) => {
  const select = event.target.closest("select[data-status-slug]");
  if (!select) {
    return;
  }

  const slug = select.dataset.statusSlug;
  const nextStatus = select.value;
  const previousValue = state.jobs.find((job) => job.slug === slug)?.status || "Not Applied";
  if (previousValue === nextStatus) {
    return;
  }

  try {
    const data = await fetchJson(`/api/jobs/${encodeURIComponent(slug)}/status`, {
      method: "POST",
      body: JSON.stringify({ status: nextStatus }),
    });
    state.jobs = state.jobs.map((job) => (job.slug === slug ? { ...job, status: data.status } : job));
    renderJobs();
  } catch (error) {
    select.value = previousValue;
    elements.runStatus.textContent = `Status update failed: ${error.message}`;
  }
});

Promise.all([loadJobs(), loadDiagnostics()]).catch((error) => {
  elements.runStatus.textContent = `Startup error: ${error.message}`;
});

initializeTheme();


// ── Quick Add ────────────────────────────────────────────────────────

const WIDE_FIELDS = new Set(["About_the_job", "Company_Intro", "Title_URL", "Company_URL"]);
const TEXTAREA_FIELDS = new Set(["About_the_job", "Company_Intro"]);

const qa = {
  toggle: document.getElementById("quick-add-toggle"),
  toggleLabel: document.getElementById("quick-add-toggle-label"),
  body: document.getElementById("quick-add-body"),
  raw: document.getElementById("quick-add-raw"),
  parseBtn: document.getElementById("quick-add-parse-btn"),
  clearBtn: document.getElementById("quick-add-clear-btn"),
  source: document.getElementById("quick-add-source"),
  form: document.getElementById("quick-add-form"),
  fieldsContainer: document.getElementById("quick-add-fields"),
  saveBtn: document.getElementById("quick-add-save-btn"),
  status: document.getElementById("quick-add-status"),
};

let qaHeaders = [];

qa.toggle.addEventListener("click", () => {
  const isHidden = qa.body.hidden;
  qa.body.hidden = !isHidden;
  qa.toggleLabel.textContent = isHidden ? "Hide" : "Show";
});

function showQAStatus(message, type) {
  qa.status.hidden = false;
  qa.status.textContent = message;
  qa.status.className = `quick-add-status status-${type}`;
}

function hideQAStatus() {
  qa.status.hidden = true;
}

function buildFormFields(headers, values = {}) {
  qa.fieldsContainer.innerHTML = "";

  headers.forEach((header) => {
    const isWide = WIDE_FIELDS.has(header);
    const isTextarea = TEXTAREA_FIELDS.has(header);
    const value = values[header] || "";
    const populated = value.trim().length > 0;

    const wrapper = document.createElement("div");
    wrapper.className = `quick-add-field${isWide ? " field-wide" : ""}`;

    const label = document.createElement("label");
    label.setAttribute("for", `qa-field-${header}`);
    label.textContent = header.replaceAll("_", " ");

    let input;
    if (isTextarea) {
      input = document.createElement("textarea");
      input.rows = 4;
    } else {
      input = document.createElement("input");
      input.type = "text";
    }
    input.id = `qa-field-${header}`;
    input.name = header;
    input.value = value;
    if (populated) {
      input.classList.add("field-populated");
    }

    input.addEventListener("input", () => {
      if (input.value.trim()) {
        input.classList.add("field-populated");
      } else {
        input.classList.remove("field-populated");
      }
    });

    wrapper.appendChild(label);
    wrapper.appendChild(input);
    qa.fieldsContainer.appendChild(wrapper);
  });
}

async function loadHeaders() {
  if (qaHeaders.length > 0) return;
  try {
    const data = await fetchJson("/api/quick-add/headers");
    qaHeaders = data.headers;
  } catch {
    qaHeaders = [
      "Company", "Title", "Category", "Location", "Title_URL", "Status",
      "Date", "About_the_job", "Posted_time", "Salary", "People_applied",
      "Company_URL", "Company_follower", "Company_size",
      "Count_of_employee_onLinkedIn", "Company_Intro", "Is this an internship",
    ];
  }
}

qa.parseBtn.addEventListener("click", async () => {
  const rawText = qa.raw.value.trim();
  if (!rawText) {
    showQAStatus("Paste some text first.", "error");
    return;
  }

  hideQAStatus();
  showQAStatus("Parsing…", "loading");

  try {
    const data = await fetchJson("/api/quick-add/parse", {
      method: "POST",
      body: JSON.stringify({ raw_text: rawText }),
    });

    await loadHeaders();

    qa.source.hidden = false;
    qa.source.textContent = `Detected source: ${data.source === "linkedin" ? "LinkedIn" : "Handshake"}`;
    qa.source.className = `quick-add-source source-${data.source}`;

    buildFormFields(qaHeaders, data.fields);

    qa.form.hidden = false;
    hideQAStatus();
  } catch (error) {
    showQAStatus(`Parse failed: ${error.message}`, "error");
  }
});

qa.clearBtn.addEventListener("click", () => {
  qa.raw.value = "";
  qa.form.hidden = true;
  qa.source.hidden = true;
  qa.fieldsContainer.innerHTML = "";
  hideQAStatus();
});

qa.form.addEventListener("reset", () => {
  setTimeout(() => {
    qa.fieldsContainer.querySelectorAll("input, textarea").forEach((el) => {
      el.classList.remove("field-populated");
    });
  }, 0);
});

qa.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showQAStatus("Saving…", "loading");

  const fields = {};
  qaHeaders.forEach((header) => {
    const input = document.getElementById(`qa-field-${header}`);
    fields[header] = input ? input.value : "";
  });

  try {
    await fetchJson("/api/quick-add/save", {
      method: "POST",
      body: JSON.stringify({ fields }),
    });

    showQAStatus("✓ Saved to jobs.xlsx successfully!", "success");

    qa.raw.value = "";
    qa.form.hidden = true;
    qa.source.hidden = true;
    qa.fieldsContainer.innerHTML = "";

    setTimeout(hideQAStatus, 4000);
  } catch (error) {
    showQAStatus(`Save failed: ${error.message}`, "error");
  }
});

