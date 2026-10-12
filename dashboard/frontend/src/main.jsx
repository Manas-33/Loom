import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  ClipboardCheck,
  Clock3,
  FileCheck2,
  FileText,
  Inbox as InboxIcon,
  LayoutGrid,
  LoaderCircle,
  MessageSquare,
  MapPin,
  Moon,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Sun,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import "./styles.css";
import "./jobs.css";

const BUCKETS = {
  generalist: "Software engineering",
  "ai-agents": "AI & agents",
  mle: "Machine learning",
  mobile: "Mobile",
};
// new-grad: the title itself says new grad / entry level; general: only the description check found it
const TITLE_MATCH = {
  "new-grad": "New-grad title",
  general: "General title",
};
const FLAGS = {
  "no-sponsorship": "No visa sponsorship",
  "location-unclear": "Location unclear",
  "no-description": "No description",
  "amazon-check": "Amazon: check account & referral",
};
// How a sweep's find is applied to when there's no company application page
const APPLY_VIA = {
  "easy-apply": "LinkedIn Easy Apply",
  handshake: "Apply on Handshake",
};
const STATUSES = [
  "Not Applied",
  "Applied",
  "OA",
  "Interview",
  "Offer",
  "Reject",
  "Ignore",
];
const fmt = (n) => Number(n || 0).toLocaleString();
const safeURL = (s) => (/^https?:\/\//i.test(s || "") ? s : undefined);
const cls = (s) => s.toLowerCase().replaceAll(" ", "-");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// A filter that holds until the browser tab closes
function useSaved(key, initial = "") {
  const [value, setValue] = useState(() => {
    try {
      return sessionStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, value);
    } catch {}
  }, [key, value]);
  return [value, setValue];
}
const matchesText = (job, q) =>
  `${job.company} ${job.title} ${job.location}`.toLowerCase().includes(q.trim().toLowerCase());
const SOURCE_LABELS = {
  simplify: "SimplifyJobs",
  linkedin: "LinkedIn",
  handshake: "Handshake",
  greenhouse: "Greenhouse",
  ashby: "Ashby",
  lever: "Lever",
  workday: "Workday",
  paste: "Added by you",
};
// Where a page's jobs came from, as a filter (only the sources those jobs have)
function SourceSelect({ jobs, value, onChange }) {
  const sources = [...new Set(jobs.flatMap((j) => j.found_via || []).concat(value ? [value] : []))].sort();
  return (
    <select className="queue-source" aria-label="Filter by source" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">All sources</option>
      {sources.map((s) => (
        <option key={s} value={s}>
          {SOURCE_LABELS[s] || s}
        </option>
      ))}
    </select>
  );
}
const fromSource = (job, source) => !source || (job.found_via || []).includes(source);
function dateLabel(s, time = false) {
  if (!s) return "Not available";
  const d = new Date(
    typeof s === "number" ? s * 1000 : s.length === 10 ? `${s}T12:00:00` : s,
  );
  return isNaN(d)
    ? s
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        ...(time ? { hour: "numeric", minute: "2-digit" } : {}),
      });
}
async function api(path, data, method = "POST") {
  const res = await fetch(
    path,
    data === undefined
      ? { cache: "no-store" }
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const body = await res.json().catch(() => ({}));
  if (!res.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Something went wrong (${res.status}). Please try again.`,
    );
  return body;
}
function IconButton({ label, children, ...props }) {
  return (
    <button className="icon-button" aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}
function CompanyMark({ name, size = "" }) {
  const tone = [...(name || "L")].reduce((n, c) => n + c.charCodeAt(0), 0) % 5;
  return (
    <span className={`company-mark tone-${tone} ${size}`} aria-hidden="true">
      {(name || "?")
        .split(/\s+/)
        .map((s) => s[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()}
    </span>
  );
}
function External({ href, children, className = "" }) {
  return safeURL(href) ? (
    <a
      className={className}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ArrowUpRight size={15} />
    </a>
  ) : null;
}
function Tags({ record, inSheet }) {
  return (
    <div className="tags">
      {inSheet?.length > 0 && (
        <span
          className="tag warning"
          title={inSheet.map((j) => `${j.title} (${j.status})`).join("\n")}
        >
          In your sheet: {inSheet[0].title} · {inSheet[0].status}
          {inSheet.length > 1 ? ` +${inSheet.length - 1}` : ""}
        </span>
      )}
      {TITLE_MATCH[record.title_match] && (
        <span
          className={`tag ${record.title_match === "new-grad" ? "soft" : "neutral"}`}
        >
          {TITLE_MATCH[record.title_match]}
        </span>
      )}
      {record.suggested_bucket && (
        <span className={`tag bucket-${record.suggested_bucket}`}>
          <span className="tag-dot" />
          {BUCKETS[record.suggested_bucket] || record.suggested_bucket}
        </span>
      )}
      {record.years_required && (
        <span className="tag neutral">{record.years_required} years</span>
      )}
      {record.grad_year && (
        <span className="tag neutral">Class of {record.grad_year}</span>
      )}
      {APPLY_VIA[record.apply_via] && (
        <span className="tag neutral">{APPLY_VIA[record.apply_via]}</span>
      )}
      {(record.flags || []).map((flag) => (
        <span
          key={flag}
          className={`tag ${flag === "no-sponsorship" || flag === "amazon-check" ? "warning" : "neutral"}`}
        >
          {FLAGS[flag] || flag}
        </span>
      ))}
    </div>
  );
}
function FileLinks({ job }) {
  return (
    <div className="file-links">
      {job.artifacts?.resume_pdf && (
        <a
          href={`/view/${encodeURIComponent(job.slug)}/Manas_Dalvi_Resume.pdf`}
          target="_blank"
          rel="noreferrer"
        >
          <FileText size={15} />
          Resume PDF
          <ArrowUpRight size={13} />
        </a>
      )}
      {job.artifacts?.cover_letter_docx && (
        <a
          href={`/api/files/${encodeURIComponent(job.slug)}/cover_letter.docx`}
        >
          <FileText size={15} />
          Cover letter
          <ArrowDown size={13} />
        </a>
      )}
    </div>
  );
}
function Empty({ title, text, icon: Icon = InboxIcon, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={28} />
      </div>
      <h2>{title}</h2>
      <p>{text}</p>
      {children}
    </div>
  );
}
function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={24} />
      <span>Getting everything ready…</span>
    </div>
  );
}
function Modal({
  title,
  children,
  confirm,
  confirmLabel,
  cancel,
  busy,
  danger,
}) {
  const ref = useRef();
  useEffect(() => {
    const d = ref.current;
    d.showModal();
    return () => d.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) cancel();
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-heading">
        <h2 id="modal-title">{title}</h2>
        <IconButton label="Close dialog" onClick={cancel} disabled={busy}>
          <X size={20} />
        </IconButton>
      </div>
      {children}
      <div className="modal-actions">
        <button className="button secondary" onClick={cancel} disabled={busy}>
          Cancel
        </button>
        <button
          className={`button ${danger ? "danger" : ""}`}
          onClick={confirm}
          disabled={busy}
        >
          {busy ? <LoaderCircle className="spin" size={16} /> : null}
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
function StatusSelect({ job, onChange }) {
  const [busy, setBusy] = useState(false);
  return (
    <span className={`status-select status-${cls(job.status)}`}>
      <span className="tag-dot" />
      <select
        aria-label={`Status for ${job.company} ${job.title}`}
        value={job.status}
        disabled={busy}
        onChange={async (e) => {
          setBusy(true);
          try {
            await onChange(job, e.target.value);
          } finally {
            setBusy(false);
          }
        }}
      >
        {STATUSES.map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      {busy ? (
        <LoaderCircle size={13} className="spin" />
      ) : (
        <ChevronDown size={13} />
      )}
    </span>
  );
}
function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || "inbox");
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "light",
  );
  const [inbox, setInbox] = useState(null),
    [jobs, setJobs] = useState(null),
    [system, setSystem] = useState(null),
    [review, setReview] = useState(null);
  const [error, setError] = useState(""),
    [systemError, setSystemError] = useState(""),
    [refreshing, setRefreshing] = useState(false);
  const [toasts, setToasts] = useState([]),
    [busy, setBusy] = useState(false),
    [leaving, setLeaving] = useState({});
  const [deleteTarget, setDeleteTarget] = useState(null);
  const busyRef = useRef(false);
  const active = route.startsWith("job/")
    ? "jobs"
    : route.startsWith("inbox/")
      ? "inbox"
      : route.startsWith("forms/")
        ? "forms"
        : route;
  function notify(text, actions = []) {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, text, actions, undoing: false }]);
    setTimeout(
      () => setToasts((prev) => prev.filter((t) => t.id !== id || t.undoing)),
      actions.length ? 6500 : 5000,
    );
  }
  async function loadSystem() {
    try {
      setSystem(await api("/api/system"));
      setSystemError("");
    } catch (e) {
      setSystemError(e.message);
    }
  }
  const loadReview = () =>
    api("/api/review")
      .then(setReview)
      .catch(() => {});
  async function reload() {
    setRefreshing(true);
    const outcomes = await Promise.allSettled([
      api("/api/inbox"),
      api("/api/jobs"),
      api("/api/review"),
    ]);
    if (outcomes[0].status === "fulfilled") setInbox(outcomes[0].value.items);
    if (outcomes[1].status === "fulfilled") setJobs(outcomes[1].value.jobs);
    if (outcomes[2].status === "fulfilled") setReview(outcomes[2].value);
    const fail = outcomes.find((r) => r.status === "rejected");
    setError(fail ? fail.reason.message : "");
    setRefreshing(false);
  }
  useEffect(() => {
    reload();
    if (location.hash !== "#system") loadSystem();
    const handle = () => {
      setRoute(location.hash.slice(1) || "inbox");
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", handle);
    return () => window.removeEventListener("hashchange", handle);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("loom-theme", theme);
    } catch {}
  }, [theme]);
  useEffect(() => {
    if (route === "system") loadSystem();
    if (route === "review") loadReview();
  }, [route]);
  const tailoring = (review?.counts?.running || 0) + (review?.counts?.queued || 0);
  const filling = (jobs || []).some((j) => ["queued", "running"].includes(fillOf(j)));
  const formsWaiting = formQueue(jobs).length;
  useEffect(() => {
    if (!tailoring && !filling) return;
    const t = setInterval(() => {
      loadReview();
      api("/api/jobs")
        .then((d) => setJobs(d.jobs))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, [tailoring > 0 || filling]);
  async function decide(action, ids, review) {
    if (!ids.length || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const { results } = await api(`/api/inbox/${action}`, review ? { ids, review: true } : { ids });
      const successful = results.filter((r) =>
        action === "keep"
          ? ["added", "merged", "duplicate", "already kept"].includes(r.result)
          : r.result === "rejected",
      );
      const failed = results.filter((r) => !successful.includes(r));
      const accepted = new Set(successful.map((r) => r.id));
      setLeaving(Object.fromEntries(successful.map((r) => [r.id, action])));
      await delay(
        matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 230,
      );
      setInbox((prev) => prev.filter((item) => !accepted.has(item.job_id)));
      setLeaving({});
      if (successful.length)
        notify(
          action === "keep"
            ? `${successful.length === 1 ? "Job" : successful.length + " jobs"} kept in My jobs`
            : `${successful.length === 1 ? "Job" : successful.length + " jobs"} rejected`,
          successful
            .filter((r) => r.undo_token)
            .map((r) => ({ id: r.id, token: r.undo_token })),
        );
      if (failed.length)
        setError(
          `${failed.length} ${failed.length === 1 ? "job could" : "jobs could"} not be updated: ${failed[0].reason || failed[0].result}. Refresh to see the latest inbox.`,
        );
      const updated = await api("/api/jobs");
      setJobs(updated.jobs);
      if (
        route.startsWith("inbox/") &&
        accepted.has(decodeURIComponent(route.slice(6)))
      )
        location.hash = "inbox";
    } catch (e) {
      setError(e.message);
    } finally {
      busyRef.current = false;
      setBusy(false);
      loadReview();
    }
  }
  async function undo(toast) {
    setToasts((prev) =>
      prev.map((t) => (t.id === toast.id ? { ...t, undoing: true } : t)),
    );
    const failures = [];
    for (const action of [...toast.actions].reverse()) {
      try {
        await api("/api/inbox/undo", action);
      } catch (e) {
        failures.push(e.message);
      }
    }
    setToasts((prev) => prev.filter((t) => t.id !== toast.id));
    await reload();
    if (failures.length) setError(failures.join(" "));
    else notify("Back in your inbox");
  }
  const refreshJobs = () =>
    api("/api/jobs")
      .then((d) => setJobs(d.jobs))
      .catch(() => {});
  async function status(job, value) {
    try {
      await api(`/api/jobs/${encodeURIComponent(job.slug)}/status`, {
        status: value,
      });
      setJobs((prev) =>
        prev.map((j) => (j.slug === job.slug ? { ...j, status: value } : j)),
      );
      notify(`Moved to ${value}`);
    } catch (e) {
      setError(e.message);
    }
  }
  async function remove() {
    setBusy(true);
    try {
      await api(
        `/api/jobs/${encodeURIComponent(deleteTarget.slug)}`,
        {},
        "DELETE",
      );
      setJobs((prev) => prev.filter((j) => j.slug !== deleteTarget.slug));
      setDeleteTarget(null);
      if (route.startsWith("job/")) location.hash = "jobs";
      notify("Job removed from your tracker");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const nav = [
    { key: "inbox", label: "Inbox", icon: InboxIcon },
    { key: "review", label: "Review", icon: ClipboardCheck },
    { key: "forms", label: "Forms", icon: FileCheck2 },
    { key: "jobs", label: "My jobs", icon: BriefcaseBusiness },
    { key: "add", label: "Add job", icon: Plus },
    { key: "system", label: "System", icon: LayoutGrid },
    { key: "settings", label: "Settings", icon: Settings2 },
  ];
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main").focus();
        }}
      >
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#inbox" aria-label="Loom home">
          <span className="brand-mark">
            <span />
            <span />
          </span>
          loom<span className="brand-period">.</span>
        </a>
        <div className="workspace-label">YOUR CAREER, IN MOTION</div>
        <nav aria-label="Main navigation">
          {nav.map(({ key, label, icon: Icon }) => (
            <a
              key={key}
              className={active === key ? "nav-link active" : "nav-link"}
              href={`#${key}`}
              aria-current={active === key ? "page" : undefined}
            >
              <Icon size={19} />
              <span>{label}</span>
              {key === "inbox" && inbox !== null && (
                <span className="nav-count">{inbox.length}</span>
              )}
              {key === "review" && !!((review?.counts?.to_review || 0) + (review?.counts?.to_glance || 0)) && (
                <span className="nav-count">{(review.counts.to_review || 0) + (review.counts.to_glance || 0)}</span>
              )}
              {key === "forms" && formsWaiting > 0 && <span className="nav-count">{formsWaiting}</span>}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span className="live-dot" />
            <span>
              Your personal workspace<small>One opportunity at a time.</small>
            </span>
          </div>
          <button
            className="theme-button"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          >
            {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            <span>
              {theme === "light" ? "Dark appearance" : "Light appearance"}
            </span>
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {nav.find((n) => n.key === active)?.label || "Job details"}
            </strong>
          </div>
          <div className="topbar-actions">
            <span className="today">
              {new Date().toLocaleDateString(undefined, {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </span>
            <IconButton
              label="Refresh dashboard"
              disabled={refreshing || busy}
              onClick={() => {
                reload();
                loadSystem();
              }}
            >
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </IconButton>
            <IconButton
              label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              <span className="mobile-theme">
                {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
              </span>
              <span className="avatar">L</span>
            </IconButton>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="page" key={active}>
            {error && (
              <div className="error-banner" role="alert">
                <span>{error}</span>
                <button onClick={reload}>Retry</button>
                <IconButton label="Dismiss error" onClick={() => setError("")}>
                  <X size={16} />
                </IconButton>
              </div>
            )}
            {route === "inbox" && (
              <InboxPage
                items={inbox}
                jobs={jobs}
                system={system}
                decide={decide}
                busy={busy}
                leaving={leaving}
              />
            )}
            {route === "review" && (
              <ReviewPage review={review} reload={loadReview} notify={notify} />
            )}
            {(route === "forms" || route.startsWith("forms/")) && (
              <FormsPage
                jobs={jobs}
                slug={route.startsWith("forms/") ? decodeURIComponent(route.slice(6)) : null}
                onJobsChanged={refreshJobs}
              />
            )}
            {route === "jobs" && (
              <JobsPage
                jobs={jobs}
                onStatus={status}
                reload={reload}
                notify={notify}
              />
            )}
            {route === "add" && (
              <AddPage
                onSaved={async (slug) => {
                  await reload();
                  notify("Job added to your tracker");
                  location.hash = `job/${encodeURIComponent(slug)}`;
                }}
              />
            )}
            {route === "settings" && <SettingsPage />}
            {route === "system" && (
              <SystemPage
                system={system}
                error={systemError}
                retry={loadSystem}
              />
            )}
            {route.startsWith("job/") && (
              <JobPage
                slug={decodeURIComponent(route.slice(4))}
                jobs={jobs}
                onStatus={status}
                onDelete={setDeleteTarget}
                onJobsChanged={refreshJobs}
              />
            )}
            {route.startsWith("inbox/") && (
              <InboxDetail
                item={inbox?.find(
                  (i) => i.job_id === decodeURIComponent(route.slice(6)),
                )}
                loading={inbox === null}
                decide={decide}
                busy={busy}
              />
            )}
            {!["inbox", "review", "forms", "jobs", "add", "system", "settings"].includes(route) &&
              !route.startsWith("job/") &&
              !route.startsWith("inbox/") &&
              !route.startsWith("forms/") && (
                <Empty
                  title="Page not found"
                  text="Head back to your inbox to keep exploring."
                >
                  <a className="button" href="#inbox">
                    Back to inbox
                  </a>
                </Empty>
              )}
          </div>
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Mobile navigation">
        {nav.map(({ key, label, icon: Icon }) => (
          <a
            key={key}
            href={`#${key}`}
            className={active === key ? "active" : ""}
            aria-current={active === key ? "page" : undefined}
          >
            <span>
              <Icon size={21} />
              {key === "inbox" && !!inbox?.length && <i />}
              {key === "review" && !!((review?.counts?.to_review || 0) + (review?.counts?.to_glance || 0)) && <i />}
              {key === "forms" && formsWaiting > 0 && <i />}
            </span>
            {key === "add" ? "Add" : label}
          </a>
        ))}
      </nav>
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div className="toast" key={t.id}>
            <CircleCheck size={19} />
            <span>{t.text}</span>
            {t.actions.length > 0 && (
              <button disabled={t.undoing} onClick={() => undo(t)}>
                {t.undoing ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Undo2 size={15} />
                )}
                Undo
              </button>
            )}
          </div>
        ))}
      </div>
      {deleteTarget && (
        <Modal
          title="Remove this job?"
          confirmLabel="Remove job"
          confirm={remove}
          cancel={() => setDeleteTarget(null)}
          busy={busy}
          danger
        >
          <p>
            <strong>{deleteTarget.title}</strong> at {deleteTarget.company} will
            be removed from My jobs, along with its resume and cover letter
            links.
          </p>
          <p className="muted small">A recovery copy is kept locally.</p>
        </Modal>
      )}
    </div>
  );
}

function InboxPage({ items, jobs, system, decide, busy, leaving }) {
  const [q, setQ] = useState(""),
    [bucket, setBucket] = useState(""),
    [source, setSource] = useState(""),
    [titleMatch, setTitleMatch] = useState(""),
    [hideFlag, setHideFlag] = useState(false),
    [gradOnly, setGradOnly] = useState(false),
    [order, setOrder] = useState("priority"),
    [filters, setFilters] = useState(false),
    [selected, setSelected] = useState(new Set()),
    [cursor, setCursor] = useState(null),
    [limit, setLimit] = useState(20);
  const filtered = (items || []).filter(
    ({ record: r }) =>
      (!bucket || r.suggested_bucket === bucket) &&
      (!source || (r.found_via || []).includes(source)) &&
      (!titleMatch || r.title_match === titleMatch) &&
      (!hideFlag || !(r.flags || []).includes("no-sponsorship")) &&
      (!gradOnly || !!r.grad_year) &&
      `${r.company} ${r.title} ${r.location}`
        .toLowerCase()
        .includes(q.toLowerCase()),
  );
  // The API sends SimplifyJobs and sweep finds first; "newest" restores the plain newest-first order
  if (order === "newest")
    filtered.sort((a, b) => (a.newest_rank ?? 0) - (b.newest_rank ?? 0));
  const priorityCount = filtered.filter((i) => i.priority).length;
  const grouped = order === "priority" && priorityCount > 0;
  const visible = filtered.slice(0, limit);
  const selectedIds = visible
    .filter((i) => selected.has(i.job_id))
    .map((i) => i.job_id);
  const filterCount =
    Number(!!source) +
    Number(!!titleMatch) +
    Number(hideFlag) +
    Number(gradOnly);
  useEffect(() => {
    setSelected(new Set());
    setLimit(20);
    setCursor(null);
  }, [q, bucket, source, titleMatch, hideFlag, gradOnly, order]);
  useEffect(() => {
    const keyboard = (e) => {
      if (
        e.target.closest("input,textarea,select,dialog,[contenteditable]") ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        busy
      )
        return;
      if (e.key === "/") {
        e.preventDefault();
        document.querySelector('[aria-label="Search inbox"]')?.focus();
        return;
      }
      const idx = visible.findIndex((i) => i.job_id === cursor);
      if (["j", "k"].includes(e.key)) {
        e.preventDefault();
        const next =
          e.key === "j"
            ? Math.min(visible.length - 1, idx + 1)
            : Math.max(0, idx - 1);
        const id = visible[next]?.job_id;
        setCursor(id);
        document
          .getElementById(`card-${id}`)
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      if (
        ["y", "n"].includes(e.key) &&
        cursor &&
        visible.some((i) => i.job_id === cursor)
      ) {
        e.preventDefault();
        const next = visible[idx + 1]?.job_id || visible[idx - 1]?.job_id;
        decide(e.key === "y" ? "keep" : "reject", [cursor]);
        setCursor(next);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [visible, cursor, busy]);
  function select(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span className="live-dot" />
            FIND YOUR NEXT CHAPTER
          </div>
          <h1>A little closer to what’s next.</h1>
          <p>
            Fresh opportunities, picked for you. Keep the ones that feel right.
          </p>
        </div>
        <a className="button secondary heading-add" href="#add">
          <Plus size={17} />
          Add a job
        </a>
      </div>
      <div className="inbox-layout">
        <section className="inbox-main" aria-label="Job inbox">
          <div className="section-title">
            <h2>
              Your inbox{" "}
              <span className="count-pill">
                {items === null ? "…" : items.length}
              </span>
            </h2>
            <label className="sort-label">
              <ArrowDown size={14} />
              <select
                aria-label="Order"
                value={order}
                onChange={(e) => setOrder(e.target.value)}
              >
                <option value="priority">SimplifyJobs & sweeps first</option>
                <option value="newest">Newest first</option>
              </select>
            </label>
          </div>
          <div className="toolbar">
            <label className="search">
              <Search size={18} />
              <input
                aria-label="Search inbox"
                type="search"
                placeholder="Search roles, companies, locations…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <kbd>/</kbd>
            </label>
            <button
              aria-label="Filters"
              className={`filter-button ${filters || filterCount ? "on" : ""}`}
              onClick={() => setFilters(!filters)}
              aria-expanded={filters}
            >
              <SlidersHorizontal size={17} />
              <span>Filters</span>
              {filterCount > 0 && <b>{filterCount}</b>}
            </button>
          </div>
          <div className="bucket-tabs" aria-label="Resume categories">
            <button
              className={!bucket ? "active" : ""}
              onClick={() => setBucket("")}
            >
              All roles
            </button>
            {Object.entries(BUCKETS).map(([key, label]) => (
              <button
                key={key}
                className={bucket === key ? "active" : ""}
                onClick={() => setBucket(key)}
              >
                {key === "generalist"
                  ? "Software"
                  : key === "mle"
                    ? "ML"
                    : label}
              </button>
            ))}
          </div>
          {filters && (
            <div className="filter-panel">
              <label>
                Source
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="">All sources</option>
                  {[
                    ...new Set(
                      (items || []).flatMap((i) => i.record.found_via || []),
                    ),
                  ]
                    .sort()
                    .map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Title
                <select
                  value={titleMatch}
                  onChange={(e) => setTitleMatch(e.target.value)}
                >
                  <option value="">All titles</option>
                  {Object.entries(TITLE_MATCH).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={hideFlag}
                  onChange={(e) => setHideFlag(e.target.checked)}
                />
                Hide jobs with no visa sponsorship
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={gradOnly}
                  onChange={(e) => setGradOnly(e.target.checked)}
                />
                Only jobs that name a graduation window
              </label>
              {filterCount > 0 && (
                <button
                  className="text-button"
                  onClick={() => {
                    setSource("");
                    setTitleMatch("");
                    setHideFlag(false);
                    setGradOnly(false);
                  }}
                >
                  Reset
                </button>
              )}
            </div>
          )}
          {items !== null && filtered.length > 0 && (
            <div className="selection-row">
              <label className="check-label">
                <input
                  type="checkbox"
                  aria-label="Select visible jobs"
                  checked={
                    visible.length > 0 && selectedIds.length === visible.length
                  }
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? new Set(visible.map((i) => i.job_id))
                        : new Set(),
                    )
                  }
                />
                <span>
                  {selectedIds.length
                    ? `${selectedIds.length} selected`
                    : `${filtered.length} ${filtered.length === 1 ? "opportunity" : "opportunities"}`}
                </span>
              </label>
              {!!selectedIds.length && (
                <div className="bulk-actions">
                  <button
                    disabled={busy}
                    onClick={() => decide("reject", selectedIds)}
                  >
                    Reject
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => decide("keep", selectedIds, true)}
                    title="Keep them, and look at each resume and its answers yourself"
                  >
                    Keep &amp; review
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => decide("keep", selectedIds)}
                  >
                    <Check size={14} />
                    Keep selected
                  </button>
                </div>
              )}
            </div>
          )}
          {items === null ? (
            <Loading />
          ) : filtered.length === 0 ? (
            <Empty
              title={items.length ? "No matches this time" : "Nothing waiting"}
              text={
                items.length
                  ? "Try another search or loosen your filters."
                  : `You’re all caught up. Last board check: ${dateLabel(system?.last_run?.finished, true)}.`
              }
            >
              {items.length > 0 && (
                <button
                  className="button secondary"
                  onClick={() => {
                    setQ("");
                    setBucket("");
                    setSource("");
                    setTitleMatch("");
                    setHideFlag(false);
                    setGradOnly(false);
                  }}
                >
                  Clear filters
                </button>
              )}
            </Empty>
          ) : (
            <div className="cards">
              <div className="inbox-table-header">
                <span>OPPORTUNITY</span>
                <span>FIT & SIGNALS</span>
                <span>YOUR NEXT STEP</span>
              </div>
              {visible.map((item, index) => (
                <React.Fragment key={item.job_id}>
                  {grouped &&
                    (index === 0 ||
                      item.priority !== visible[index - 1].priority) && (
                      <div className="inbox-group">
                        {item.priority
                          ? "From SimplifyJobs & your sweeps"
                          : "From company job boards"}
                        <span>
                          {item.priority
                            ? priorityCount
                            : filtered.length - priorityCount}
                        </span>
                      </div>
                    )}
                  <InboxCard
                    item={item}
                    index={index}
                    selected={selected.has(item.job_id)}
                    onSelect={() => select(item.job_id)}
                    focused={cursor === item.job_id}
                    decide={decide}
                    busy={busy}
                    leaving={leaving[item.job_id]}
                  />
                </React.Fragment>
              ))}
            </div>
          )}
          {filtered.length > limit && (
            <button
              className="button secondary load-more"
              onClick={() => setLimit(limit + 20)}
            >
              Show more opportunities
              <ChevronDown size={16} />
            </button>
          )}
          <div className="keyboard-hint">
            <kbd>j</kbd>
            <kbd>k</kbd> navigate <span />
            <kbd>y</kbd> keep <span />
            <kbd>n</kbd> reject
          </div>
          <p className="swipe-hint">Swipe right to keep · left to reject</p>
        </section>
      </div>
    </>
  );
}
function InboxCard({
  item,
  index,
  selected,
  onSelect,
  focused,
  decide,
  busy,
  leaving,
}) {
  const r = item.record,
    [expanded, setExpanded] = useState(false),
    [drag, setDrag] = useState(0),
    touch = useRef(null);
  return (
    <article
      id={`card-${item.job_id}`}
      className={`job-card ${selected ? "selected" : ""} ${focused ? "keyboard-focus" : ""} ${leaving ? `leaving-${leaving}` : ""} ${drag > 45 ? "swipe-keep" : drag < -45 ? "swipe-reject" : ""}`}
      style={{
        "--entrance-delay": `${Math.min(index, 5) * 35}ms`,
        "--swipe": `${drag}px`,
      }}
      onPointerDown={(e) => {
        if (
          e.pointerType === "touch" &&
          !e.target.closest("button,a,input,select")
        )
          touch.current = { x: e.clientX, y: e.clientY };
      }}
      onPointerMove={(e) => {
        if (touch.current) {
          const dx = e.clientX - touch.current.x,
            dy = e.clientY - touch.current.y;
          if (Math.abs(dy) > 35 && Math.abs(dy) > Math.abs(dx)) {
            touch.current = null;
            setDrag(0);
          } else if (Math.abs(dx) > 15)
            setDrag(Math.max(-125, Math.min(125, dx)));
        }
      }}
      onPointerUp={() => {
        if (Math.abs(drag) > 85 && !busy)
          decide(drag > 0 ? "keep" : "reject", [item.job_id]);
        touch.current = null;
        setDrag(0);
      }}
      onPointerCancel={() => {
        touch.current = null;
        setDrag(0);
      }}
    >
      <div className="opportunity-summary">
        <div className="opportunity-heading">
          <label className="card-select">
            <input
              type="checkbox"
              aria-label={`Select ${r.company} ${r.title}`}
              checked={selected}
              onChange={onSelect}
            />
          </label>
          <CompanyMark name={r.company} />
          <div className="opportunity-title">
            <h3>
              {safeURL(r.url) ? (
                <External href={r.url}>{r.title}</External>
              ) : (
                r.title
              )}
            </h3>
            <div className="opportunity-meta">
              <strong>{r.company}</strong>
              <span>·</span>
              <span className="source-label">
                {(r.found_via || []).join(" / ") || "Company board"}
              </span>
              {r.posted_time && (
                <>
                  <span>·</span>
                  <span>{dateLabel(r.posted_time)}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="opportunity-context">
          <div className="location">
            <MapPin size={13} />
            <span>{r.location || "Location not specified"}</span>
          </div>
          {item.reason && (
            <div className="why">
              <Sparkles size={14} />
              <p>{item.reason}</p>
            </div>
          )}
          <button
            className="description-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Close description" : "Read description"}
            <ChevronDown size={14} className={expanded ? "rotated" : ""} />
          </button>
        </div>
      </div>
      <div className="opportunity-fit">
        <Tags record={r} inSheet={item.in_sheet} />
      </div>
      <div className="opportunity-actions">
        <div className="decision-actions">
          <button
            className="button reject-button"
            disabled={busy}
            onClick={() => decide("reject", [item.job_id])}
          >
            <X size={15} />
            Reject
          </button>
          <button
            className="button keep-button"
            disabled={busy}
            onClick={() => decide("keep", [item.job_id])}
          >
            <Check size={16} />
            Keep
          </button>
        </div>
        <button
          className="text-button keep-review"
          disabled={busy}
          title="Keep it, and look at the resume and answers yourself before the form is filled"
          onClick={() => decide("keep", [item.job_id], true)}
        >
          Keep &amp; review myself
        </button>
        <External href={safeURL(r.url) || r.apply_url} className="posting-link">
          Open posting
        </External>
      </div>
      {expanded && (
        <div className="expanded-description">
          <div className="description-header">
            <strong>Job description</strong>
            <a
              className="text-link"
              href={`#inbox/${encodeURIComponent(item.job_id)}`}
            >
              Full job page
              <ArrowUpRight size={14} />
            </a>
          </div>
          <p>{r.description || "No description available."}</p>
        </div>
      )}
    </article>
  );
}

function JobsPage({ jobs, onStatus, reload, notify }) {
  const [picked, setPicked] = useState(new Set());
  const [bulkNote, setBulkNote] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [q, setQ] = useState("");
  // Opens on Not Applied (what's left to do); a different pick holds until the browser tab closes
  const [status, setStatus] = useState(() => {
    try {
      return sessionStorage.getItem("loom-jobs-status") ?? "Not Applied";
    } catch {
      return "Not Applied";
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem("loom-jobs-status", status);
    } catch {}
  }, [status]);
  const [limit, setLimit] = useState(30);
  const filtered = (jobs || []).filter(
    (j) =>
      (!status || j.status === status) &&
      `${j.company} ${j.title} ${j.location}`
        .toLowerCase()
        .includes(q.toLowerCase()),
  );
  const notApplied = jobs?.filter((j) => j.status === "Not Applied").length;
  const readyToFill = (jobs || []).filter(
    (j) =>
      j.status === "Not Applied" &&
      j.artifacts?.resume_pdf &&
      !["queued", "running", "submitted"].includes(j.artifacts?.tailor?.apply),
  );
  const pick = (slug) => {
    const next = new Set(picked);
    next.has(slug) ? next.delete(slug) : next.add(slug);
    setPicked(next);
    setBulkNote("");
  };
  // One action on every selected job; the note says what happened, and the list reloads after
  async function bulk(run) {
    setBulkBusy(true);
    setBulkNote("");
    try {
      setBulkNote(await run([...picked]));
      setPicked(new Set());
      await reload?.();
    } catch (e) {
      setBulkNote(e.message);
    } finally {
      setBulkBusy(false);
    }
  }
  const fillPicked = () =>
    bulk(async (slugs) => {
      const res = await api("/api/apply/queue", { slugs });
      return (
        `${res.queued.length} queued to fill, one after another in Chrome` +
        (res.skipped.length ? ` · ${res.skipped.length} skipped (${res.skipped[0].reason})` : "")
      );
    });
  const tailorPicked = () =>
    bulk(async (slugs) => {
      const res = await api("/api/tailor/queue", { slugs });
      const rest = slugs.length - res.queued.length;
      return `${res.queued.length} queued to tailor` + (rest ? ` · ${rest} already tailored or tailoring` : "");
    });
  const statusPicked = (value) =>
    bulk(async (slugs) => {
      for (const slug of slugs)
        await api(`/api/jobs/${encodeURIComponent(slug)}/status`, { status: value });
      return `${slugs.length} moved to ${value}`;
    });
  const reviewPicked = (review) =>
    bulk(async (slugs) => {
      for (const slug of slugs)
        await api(`/api/jobs/${encodeURIComponent(slug)}/review-mode`, { review });
      return review ? `${slugs.length} set to review yourself` : `${slugs.length} set to go through automatically`;
    });
  const deletePicked = () => {
    if (!confirm(`Delete ${picked.size} job${picked.size === 1 ? "" : "s"} from your tracker? Recovery copies are kept in data/trash.`))
      return;
    bulk(async (slugs) => {
      for (const slug of slugs) await api(`/api/jobs/${encodeURIComponent(slug)}`, {}, "DELETE");
      notify?.(`${slugs.length} job${slugs.length === 1 ? "" : "s"} removed from your tracker`);
      return "";
    });
  };

  useEffect(() => {
    setLimit(30);
  }, [q, status]);

  return (
    <div className="jobs-collection">
      <div className="page-heading">
        <div>
          <div className="eyebrow">EVERY POSSIBILITY, IN ONE PLACE</div>
          <h1>My jobs</h1>
          <p>From a promising role to an offer. Keep track of every step.</p>
        </div>
        <a href="#add" className="button">
          <Plus size={17} />
          Add a job
        </a>
      </div>
      <div className="collection-tools">
        <div className="collection-totals" aria-label="Tracker summary">
          <span>
            <strong>{jobs ? fmt(jobs.length) : "—"}</strong> total jobs
          </span>
          <span className="summary-separator" aria-hidden="true" />
          <button
            className={status === "Not Applied" ? "is-active" : ""}
            onClick={() =>
              setStatus(status === "Not Applied" ? "" : "Not Applied")
            }
            aria-pressed={status === "Not Applied"}
            title="Filter jobs you have not applied to"
          >
            <i />
            <strong>
              {notApplied === undefined ? "—" : fmt(notApplied)}
            </strong>{" "}
            not applied
          </button>
        </div>
        <div className="collection-filters">
          <label className="search">
            <Search size={17} />
            <input
              type="search"
              aria-label="Search my jobs"
              placeholder="Search your jobs…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <label className="collection-status-filter">
            <span className="sr-only">Filter by status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="collection-workbench">
        <div className="collection-list-area">
          {jobs === null ? (
            <Loading />
          ) : !filtered.length ? (
            <Empty
              title={
                jobs.length ? "No jobs match" : "Your next move starts here"
              }
              text={
                jobs.length
                  ? "Try a different search or status."
                  : "Keep a role from your inbox, or add a posting you found."
              }
            >
              {jobs.length ? (
                <button
                  className="button secondary"
                  onClick={() => {
                    setQ("");
                    setStatus("");
                  }}
                >
                  Clear filters
                </button>
              ) : (
                <a href="#inbox" className="button secondary">
                  Explore inbox
                  <ArrowRight size={16} />
                </a>
              )}
            </Empty>
          ) : (
            <section className="collection-board" aria-label="Tracked jobs">
              <div className="bulk-bar">
                {picked.size > 0 ? (
                  <>
                    <strong>{picked.size} selected</strong>
                    <button className="button" disabled={bulkBusy} onClick={fillPicked}>
                      <Sparkles size={15} />
                      Fill applications
                    </button>
                    <button className="button secondary" disabled={bulkBusy} onClick={tailorPicked}>
                      Tailor
                    </button>
                    <select
                      className="bulk-select"
                      disabled={bulkBusy}
                      value=""
                      onChange={(e) => e.target.value && statusPicked(e.target.value)}
                      aria-label="Set status for the selected jobs"
                    >
                      <option value="">Set status…</option>
                      {STATUSES.map((st) => (
                        <option key={st}>{st}</option>
                      ))}
                    </select>
                    <select
                      className="bulk-select"
                      disabled={bulkBusy}
                      value=""
                      onChange={(e) => e.target.value && reviewPicked(e.target.value === "review")}
                      aria-label="Review choice for the selected jobs"
                    >
                      <option value="">Review…</option>
                      <option value="review">I'll review them</option>
                      <option value="auto">Go through automatically</option>
                    </select>
                    <button className="button secondary danger-text" disabled={bulkBusy} onClick={deletePicked}>
                      <Trash2 size={14} />
                      Delete
                    </button>
                    <button className="text-button" disabled={bulkBusy} onClick={() => setPicked(new Set())}>
                      Clear
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="text-button"
                      disabled={!readyToFill.length}
                      onClick={() => setPicked(new Set(readyToFill.map((j) => j.slug)))}
                      title="Not applied, with a resume ready, and not filled yet"
                    >
                      Select all ready to fill ({readyToFill.length})
                    </button>
                    <button
                      className="text-button"
                      disabled={!filtered.length}
                      onClick={() => setPicked(new Set(filtered.map((j) => j.slug)))}
                      title="Every job matching the search and status filter"
                    >
                      Select all shown ({filtered.length})
                    </button>
                  </>
                )}
                {bulkBusy && <LoaderCircle className="spin" size={15} />}
                {bulkNote && <span className="muted small">{bulkNote}</span>}
              </div>
              <div className="collection-columns" aria-hidden="true">
                <span className="column-number">#</span>
                <span>ROLE / COMPANY</span>
                <span className="column-location">LOCATION</span>
                <span>STATUS</span>
                <span>POSTING</span>
                <span className="column-chevron" />
              </div>
              {filtered.slice(0, limit).map((job, index) => (
                <article
                  key={job.slug}
                  className={`collection-row progress-${cls(job.status)}`}
                >
                  <span className="collection-number" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="collection-opportunity">
                    <input
                      type="checkbox"
                      className="collection-pick"
                      checked={picked.has(job.slug)}
                      onChange={() => pick(job.slug)}
                      aria-label={`Select ${job.title} at ${job.company}`}
                    />
                    <CompanyMark name={job.company} />
                    <div className="collection-role-content">
                      <a
                        className="collection-role-title"
                        href={`#job/${encodeURIComponent(job.slug)}`}
                      >
                        {job.title}
                      </a>
                      <div className="collection-byline">
                        <span>{job.company}</span>
                        <FileLinks job={job} />
                        <TailorChip job={job} />
                        <CoverageChip job={job} />
                      </div>
                    </div>
                  </div>
                  <div
                    className="collection-location"
                    title={job.location || "Location not specified"}
                  >
                    <MapPin size={13} />
                    <span>{job.location || "Location not specified"}</span>
                  </div>
                  <div className="collection-status">
                    <StatusSelect job={job} onChange={onStatus} />
                  </div>
                  <div className="collection-posting">
                    {safeURL(job.url) || safeURL(job.apply_url) ? (
                      <External
                        href={safeURL(job.url) || job.apply_url}
                        className="posting-link"
                      >
                        Open posting
                      </External>
                    ) : (
                      <span className="missing-posting">No posting link</span>
                    )}
                  </div>
                  <a
                    className="collection-open"
                    aria-label={`View details for ${job.company} ${job.title}`}
                    href={`#job/${encodeURIComponent(job.slug)}`}
                  >
                    <ChevronRight size={17} />
                  </a>
                </article>
              ))}
            </section>
          )}
          <div className="collection-footer">
            <span>
              {Math.min(limit, filtered.length)} of {filtered.length} jobs
              {q || status ? " match your filters" : " · Most recent first"}
            </span>
            {filtered.length > limit && (
              <button
                className="button secondary"
                onClick={() => setLimit(limit + 30)}
              >
                Show more
                <ChevronDown size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailContent({ record, children, files, inSheet }) {
  return (
    <>
      <div className="detail-heading">
        <CompanyMark name={record.company} size="large" />
        <div>
          <div className="eyebrow">{record.company}</div>
          <h1>{record.title}</h1>
          <div className="location">
            <MapPin size={16} />
            {record.location || "Location not specified"}
          </div>
        </div>
      </div>
      <Tags record={record} inSheet={inSheet} />
      <div className="detail-grid">
        <section className="surface description-surface">
          <div className="section-title">
            <h2>About the role</h2>
            <External href={record.url} className="text-link">
              Original posting
            </External>
          </div>
          <div className="job-description">
            {record.description || "No description is available for this job."}
          </div>
          {record.company_intro && (
            <>
              <h2>About the company</h2>
              <p className="job-description">{record.company_intro}</p>
            </>
          )}
        </section>
        <aside className="detail-sidebar">
          <div className="surface detail-actions">
            <h3>Your next step</h3>
            {children}
            <External href={record.apply_url || record.url} className="button">
              Open application
            </External>
            {files}
            <div className="detail-facts">
              {record.suggested_bucket && (
                <div>
                  <span>Suggested resume</span>
                  <strong>
                    {BUCKETS[record.suggested_bucket] ||
                      record.suggested_bucket}
                  </strong>
                </div>
              )}
              {record.salary && (
                <div>
                  <span>Salary</span>
                  <strong>{record.salary}</strong>
                </div>
              )}
              {record.posted_time && (
                <div>
                  <span>Posted</span>
                  <strong>{dateLabel(record.posted_time)}</strong>
                </div>
              )}
            </div>
          </div>
          <div className="coming-next">
            <Sparkles size={19} />
            <h3>A little more help, soon.</h3>
            <p>
              Resume tailoring, application answers, and assisted form filling
              will live here.
            </p>
            <span className="tag neutral">Coming later</span>
          </div>
        </aside>
      </div>
    </>
  );
}
const TWEAK_STATUS = {
  pending: "Waiting for you",
  applied: "Applied",
  rejected: "Skipped",
  "didn't fit": "Didn't fit",
};
const ENGINE_LABEL = { claude: "Claude", codex: "Codex", dashboard: "Dashboard" };
// Tweak text is LaTeX; show it the way it reads on the page
function texText(tex) {
  let s = String(tex || "")
    .replace(/\$\|\$|\$\\mid\$/g, "|")
    .replace(/\}\{/g, "} {");
  for (let prev = ""; prev !== s; ) {
    prev = s;
    s = s.replace(/\\(textbf|emph|textit|underline)\{([^{}]*)\}/g, "$2");
  }
  return s
    .replace(/\\href\{[^{}]*\}\s*\{([^{}]*)\}/g, "$1")
    .replace(/\\resumeItem\{/g, "\n• ")
    .replace(/\\(resumeItemListStart|resumeItemListEnd|resumeProjectHeading|resumeSubheading)\b/g, "")
    .replace(/\\vspace\{[^{}]*\}/g, "")
    .replace(/\\([%&$#_])/g, "$1")
    .replace(/\\\\/g, " ")
    .replace(/[{}]/g, "")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
}
function elapsedLabel(since) {
  const secs = Math.max(0, Math.round((Date.now() - new Date(since)) / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}
const tailorBase = (slug) => `/api/jobs/${encodeURIComponent(slug)}/tailor`;
const resumeFile = (slug, file, version = "") =>
  `/view/${encodeURIComponent(slug)}/${file}?v=${encodeURIComponent(version)}`;
// Tweak choices → the decide request: Use = approve, Skip = reject, Change = feedback
function decisionBody(choices, feedback) {
  const body = { approve: [], reject: [], change: {} };
  for (const [id, c] of Object.entries(choices)) {
    if (c === "change") {
      if ((feedback[id] || "").trim()) body.change[id] = feedback[id];
    } else body[c === "use" ? "approve" : "reject"].push(Number(id));
  }
  return body;
}
const hasDecision = (b) =>
  b.approve.length || b.reject.length || Object.keys(b.change).length;
function TailorChip({ job }) {
  const t = job.artifacts?.tailor;
  if (!t) return null;
  const FILL = {
    queued: ["Filling soon", "soft"],
    running: ["Filling in Chrome…", "soft"],
    ready_to_submit: ["Ready to submit", "soft"],
    needs_you: ["Form needs you", "warning"],
    blocked: ["Fill blocked", "warning"],
    failed: ["Fill failed", "warning"],
  };
  const [label, tone] = FILL[t.apply]
    ? FILL[t.apply]
    : t.status === "queued"
      ? ["Queued to tailor", "neutral"]
      : t.status === "running"
        ? ["Tailoring…", "soft"]
        : t.status === "failed"
          ? ["Couldn’t tailor", "warning"]
          : t.blocker
            ? ["Sponsorship blocker", "warning"]
            : !t.reviewed
              ? [t.pending ? `${t.pending} tweak${t.pending > 1 ? "s" : ""} to review` : "Ready to review", "soft"]
              : ["queued", "running"].includes(t.answers?.status)
                ? ["Drafting answers…", "soft"]
                : t.answers?.status === "ready" && !t.answers.reviewed
                  ? ["Answers to review", "soft"]
                  : t.answers?.needs_you
                    ? [`${t.answers.needs_you} answer${t.answers.needs_you > 1 ? "s" : ""} need you`, "warning"]
                    : ["Resume ready", "neutral"];
  if (FORM_GROUPS[t.apply] && job.status === "Not Applied")
    return (
      <a className={`tag ${tone} tailor-chip`} href={`#forms/${encodeURIComponent(job.slug)}`}>
        {label}
      </a>
    );
  const reviewable =
    (!t.reviewed && ["ready", "failed"].includes(t.status)) ||
    (t.reviewed && t.answers?.status === "ready" && !t.answers.reviewed);
  return reviewable ? (
    <a className={`tag ${tone} tailor-chip`} href="#review">{label}</a>
  ) : (
    <span className={`tag ${tone} tailor-chip`}>{label}</span>
  );
}
function BlockerBanner({ result }) {
  if (!result?.sponsorship_blocker) return null;
  return (
    <div className="tailor-blocker" role="alert">
      <strong>Sponsorship blocker</strong>
      <p>{result.boost?.sponsorship}</p>
    </div>
  );
}
function BlockedNotice({ turns, audited = false }) {
  const blocked = (turns || []).flatMap((t) =>
    (t.denied || []).map((d) =>
      typeof d === "string" ? { at: t.at, tool: d, detail: "" } : { at: t.at, ...d },
    ),
  );
  if (!blocked.length) return null;
  return (
    <div className="tailor-blocked" role="note">
      <strong>
        {audited
          ? `The audit flagged ${blocked.length === 1 ? "something" : `${blocked.length} things`} Codex ran`
          : `${ENGINE_LABEL[turns[turns.length - 1]?.engine] || "The assistant"} tried ${blocked.length === 1 ? "something" : `${blocked.length} things`} it isn’t allowed to do`}
      </strong>
      <p>
        {audited
          ? "Nothing stopped these: Codex’s browser limits are instructions, not enforced. Check the Chrome tab and the application record carefully before submitting."
          : "It was stopped each time and carried on without it. If the result looks incomplete, this is probably why; tell Claude Code which of these to allow."}
      </p>
      <ul>
        {blocked.map((b, i) => (
          <li key={i}>
            <span>{dateLabel(b.at, true)}</span> {b.tool}
            {b.detail && <code>{b.detail}</code>}
          </li>
        ))}
      </ul>
    </div>
  );
}
function ResumeComment({
  onSend,
  disabled,
  resetKey,
  label = "Comment on this resume",
  placeholder = "Ask for a change or a question, e.g. “Use the Moment project instead of OttoNote” or “Would Orbit fit better here?”",
  hint = "Goes to this job’s tailoring session, with any Use/Skip you picked. ⌘↵ sends.",
}) {
  const [text, setText] = useState("");
  useEffect(() => setText(""), [resetKey]);
  const send = () => text.trim() && onSend(text.trim());
  return (
    <div className="resume-comment">
      <label htmlFor={`comment-${resetKey}`}>
        <MessageSquare size={14} />
        {label}
      </label>
      <textarea
        id={`comment-${resetKey}`}
        value={text}
        disabled={disabled}
        maxLength={2000}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div className="resume-comment-bar">
        <span className="muted small">{hint}</span>
        <button className="button secondary" disabled={disabled || !text.trim()} onClick={send}>
          Send comment
        </button>
      </div>
    </div>
  );
}
function CommentReply({ turns, message }) {
  const last = (turns || [])[turns?.length - 1];
  if (!last?.comment) return null;
  return (
    <div className="comment-reply">
      <p>
        <strong>You:</strong> {last.comment}
      </p>
      <p>
        <strong>Reply:</strong> {message}
      </p>
    </div>
  );
}
function TweakCard({ t, choice, onChoose, feedback, onFeedback, disabled, coverage }) {
  const wouldAdd = t.status === "pending" ? coverage?.would_add?.[t.id] : null;
  const added = t.status === "applied" ? (coverage?.gained || []).filter((k) => k.tweak === t.id) : [];
  return (
    <article className={`tweak-card status-${t.status.replace(/\W/g, "")} ${choice ? `chose-${choice}` : ""}`}>
      <header>
        <strong>{t.summary}</strong>
        <span className="tweak-status">{TWEAK_STATUS[t.status] || t.status}</span>
      </header>
      <div className="tweak-diff">
        <p className="tweak-before">{texText(t.before)}</p>
        <p className="tweak-after">{texText(t.after)}</p>
      </div>
      <p className="tweak-why">{t.why}</p>
      {wouldAdd && (
        <p className="tweak-gain">
          {[
            wouldAdd.keywords.length ? `Adds ${wouldAdd.keywords.join(", ")}` : "",
            wouldAdd.loses?.length ? `drops ${wouldAdd.loses.join(", ")}` : "",
            wouldAdd.points === 0
              ? "no change in coverage"
              : `${wouldAdd.points > 0 ? "+" : ""}${wouldAdd.points}% coverage`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {added.length > 0 && <p className="tweak-gain">Added {added.map((k) => k.keyword).join(", ")}</p>}
      <details className="tweak-evidence">
        <summary>Evidence from your CV</summary>
        {t.evidence}
      </details>
      {!disabled && (
        <div className="tweak-actions">
          {t.status !== "applied" && (
            <button className={`chip ${choice === "use" ? "on" : ""}`} onClick={() => onChoose(t.id, "use")}>
              <Check size={13} />
              {t.status === "rejected" ? "Use instead" : "Use"}
            </button>
          )}
          {t.status !== "rejected" && (
            <button className={`chip ${choice === "skip" ? "on" : ""}`} onClick={() => onChoose(t.id, "skip")}>
              {t.status === "applied" ? <Undo2 size={13} /> : <X size={13} />}
              {t.status === "applied" ? "Undo" : "Skip"}
            </button>
          )}
          <button className={`chip ${choice === "change" ? "on" : ""}`} onClick={() => onChoose(t.id, "change")}>
            Change…
          </button>
        </div>
      )}
      {choice === "change" && (
        <textarea
          className="tweak-feedback"
          autoFocus
          placeholder="What should change? e.g. keep Go in the line, or make it shorter"
          value={feedback || ""}
          onChange={(e) => onFeedback(t.id, e.target.value)}
        />
      )}
    </article>
  );
}
function useChoices(key) {
  const [choices, setChoices] = useState({}),
    [feedback, setFeedback] = useState({});
  useEffect(() => {
    setChoices({});
    setFeedback({});
  }, [key]);
  return {
    choices,
    feedback,
    choose: (id, c) =>
      setChoices((prev) => {
        const next = { ...prev };
        if (next[id] === c) delete next[id];
        else next[id] = c;
        return next;
      }),
    setFeedbackFor: (id, text) => setFeedback((prev) => ({ ...prev, [id]: text })),
  };
}
function Coverage({ coverage: c }) {
  if (!c) return null;
  const moved = c.now !== c.as_is || c.applied > 0;  // tweaks in use: show the before → after even when equal
  const names = (items) => items.map((k) => k.keyword).join(", ");
  return (
    <div className="coverage" aria-label="Coverage score">
      <div className="coverage-head">
        <h3>Coverage</h3>
        <p className="coverage-numbers">
          {moved && (
            <>
              <span className="coverage-was">{c.as_is}%</span>
              <ArrowRight size={14} aria-label="now" />
            </>
          )}
          <strong>{c.now}%</strong>
          <span className="muted">
            {moved ? ` with ${c.applied} tweak${c.applied === 1 ? "" : "s"}` : " as-is"} · most you can reach{" "}
            {c.max}%
          </span>
        </p>
      </div>
      <div
        className="coverage-bar"
        role="img"
        aria-label={`${c.now}% of what the posting asks for is on your resume; ${c.max}% is the most you can claim`}
      >
        <span className="coverage-max" style={{ width: `${c.max}%` }} />
        <span className="coverage-now" style={{ width: `${c.now}%` }} />
        {moved && <span className="coverage-mark" style={{ left: `${c.as_is}%` }} />}
      </div>
      <p className="coverage-line">
        Required {c.tiers.min.now}/{c.tiers.min.total} · Preferred {c.tiers.pref.now}/{c.tiers.pref.total}{" "}
        <span className="muted">(preferred counts double)</span>
      </p>
      {c.gained.length > 0 && (
        <p className="coverage-line">
          <strong>Added by tweaks:</strong> {names(c.gained)}
        </p>
      )}
      {c.lost.length > 0 && (
        <p className="tailor-warning">
          Lost:{" "}
          {c.lost
            .map((k) => `${k.keyword}${k.tweak ? ` (tweak ${k.tweak} replaced the line that covered it)` : ""}`)
            .join(", ")}
        </p>
      )}
      {c.vouched?.length > 0 && (
        <p className="coverage-line">
          <strong>On your word:</strong> {names(c.vouched)}{" "}
          <span className="muted">(not in cv.md yet: add the evidence there so it holds up in an interview)</span>
        </p>
      )}
      {c.open.length > 0 && (
        <p className="coverage-line">
          <strong>Could still add:</strong> {names(c.open)}
        </p>
      )}
      {c.cannot_claim.length > 0 && (
        <p className="coverage-line muted">
          <strong>Can’t claim:</strong> {names(c.cannot_claim)}
        </p>
      )}
      {c.unverified.length > 0 && (
        <p className="coverage-line muted">
          <strong>Not counted</strong> (couldn’t find it on the resume): {names(c.unverified)}
        </p>
      )}
    </div>
  );
}
function CoverageChip({ job }) {
  const c = job.artifacts?.tailor?.coverage;
  if (!c) return null;
  return (
    <span
      className="tag neutral coverage-chip"
      title={`Resume coverage: ${c.as_is}% as-is, ${c.now}% now, ${c.max}% the most you can reach`}
    >
      {c.now}% covered
    </span>
  );
}
function Checks({ build }) {
  if (!build?.checks) return null;
  return (
    <div className="tailor-checks">
      {Object.entries(build.checks).map(([name, ok]) => (
        <span key={name} className={`tag ${ok ? "soft" : "warning"}`}>
          {ok ? <Check size={11} /> : <X size={11} />}
          {name}
        </span>
      ))}
      {(build.warnings || []).map((w) => (
        <p key={w} className="tailor-warning">{w}</p>
      ))}
    </div>
  );
}
function ResumePreview({ slug, version, small }) {
  return (
    <a
      className={`tailor-preview ${small ? "small" : ""}`}
      href={resumeFile(slug, "Manas_Dalvi_Resume.pdf", version)}
      target="_blank"
      rel="noreferrer"
      title="Open the PDF"
    >
      <img
        src={resumeFile(slug, "preview.png", version)}
        alt="Resume preview; changed lines are highlighted"
        onError={(e) => (e.currentTarget.style.display = "none")}
      />
      <span>
        Open PDF <ArrowUpRight size={13} />
      </span>
    </a>
  );
}
function TailorDetails({ result, onRequest, locked, openBoost }) {
  return (
    <>
      <details className="tailor-details">
        <summary>Keyword check</summary>
        <p>{result.preferred_coverage}</p>
        <h4>On your resume</h4>
        <div className="chip-row">
          {(result.keywords?.present || []).map((k) => {
            const name = typeof k === "string" ? k : k.keyword;
            return (
              <span key={name} className="tag neutral" title={typeof k === "string" ? undefined : k.quote}>
                {name}
              </span>
            );
          })}
        </div>
        <h4>Missing, but you can back it up</h4>
        <ul>
          {(result.keywords?.missing || []).map((k) => (
            <li key={k.keyword}>
              <strong>{k.keyword}</strong> <em>{k.tier === "pref" ? "preferred" : "required"}</em> {k.note}
            </li>
          ))}
        </ul>
        <h4>Can’t claim</h4>
        <ul>
          {(result.keywords?.not_claimable || []).map((k) => (
            <li key={k.keyword}>
              <strong>{k.keyword}</strong> <em>{k.tier === "pref" ? "preferred" : "required"}</em> {k.note}
            </li>
          ))}
        </ul>
      </details>
      <details className="tailor-details" open={openBoost}>
        <summary>Boost your odds</summary>
        <dl>
          <dt>Sponsorship</dt>
          <dd>{result.boost?.sponsorship}</dd>
          <dt>Hiring process</dt>
          <dd>{result.boost?.process}</dd>
          <dt>Referrals</dt>
          <dd>
            <ul>
              {(result.boost?.referrals || []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </dd>
          <dt>Outreach</dt>
          <dd>
            {result.boost?.outreach}{" "}
            {onRequest && (
              <button className="text-button" disabled={locked} onClick={() => onRequest("Draft the outreach note.")}>
                Draft a note
              </button>
            )}
          </dd>
          <dt>Timing</dt>
          <dd>{result.boost?.timing}</dd>
        </dl>
        {(result.reminders || []).length > 0 && (
          <ul className="tailor-reminders">
            {result.reminders.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </details>
    </>
  );
}
function TailorPanel({ slug, onChanged }) {
  const [state, setState] = useState(null),
    [error, setError] = useState(""),
    [sending, setSending] = useState(false),
    [, tick] = useState(0);
  const { choices, feedback, choose, setFeedbackFor } = useChoices(`${slug}|${state?.updated}`);
  const busyStatus = state?.status === "running" || state?.status === "queued";
  const load = () =>
    api(tailorBase(slug))
      .then((next) =>
        setState((prev) => {
          if (["running", "queued"].includes(prev?.status) && !["running", "queued"].includes(next.status))
            onChanged?.();
          return next;
        }),
      )
      .catch((e) => setError(e.message));
  const answering =
    ["queued", "running"].includes(state?.answers?.status) || ["queued", "running"].includes(state?.apply?.status);
  useEffect(() => {
    setState(null);
    load();
  }, [slug]);
  useEffect(() => {
    if (!busyStatus && !answering) return;
    const t = setInterval(() => {
      load();
      tick((n) => n + 1);
    }, 3000);
    return () => clearInterval(t);
  }, [busyStatus, answering]);
  async function send(path, body) {
    setSending(true);
    setError("");
    try {
      setState(await api(path, body));
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }
  const start = (restart = false) => send(tailorBase(slug), { restart });
  const decide = (body) => send(`${tailorBase(slug)}/decide`, body);
  const setReview = (review) => send(`/api/jobs/${encodeURIComponent(slug)}/review-mode`, { review });
  const result = state?.result;
  const tweaks = result?.tweaks || [];
  const body = decisionBody(choices, feedback);
  const locked = busyStatus || sending;
  if (state === null && !error) return null;
  return (
    <>
    <section id="tailor-panel" className="surface tailor-panel" aria-label="Tailored resume">
      <div className="section-title">
        <h2>Tailored resume</h2>
        <label className="check-label review-toggle" title="Off: tweaks and answers go through, and you check everything in the filled form before Submit">
          <input
            type="checkbox"
            checked={Boolean(state?.review)}
            disabled={locked}
            onChange={(e) => setReview(e.target.checked)}
          />
          Review this job myself
        </label>
        {result && !busyStatus && (
          <button
            className="text-button"
            disabled={locked}
            onClick={() => {
              if (confirm("Start over? This picks the resume again and replaces these tweaks.")) start(true);
            }}
          >
            <RefreshCw size={14} />
            Start over
          </button>
        )}
      </div>
      {error && <p className="tailor-error">{error}</p>}
      {state?.status === "none" && (
        <div className="tailor-empty">
          <p>
            Picks the right resume, checks which of the job’s keywords you can back up, and suggests
            up to 3 small tweaks. Runs in the background; you’ll find it in Review when it’s done.
          </p>
          <button className="button" disabled={locked} onClick={() => start()}>
            <Sparkles size={16} />
            Tailor resume
          </button>
        </div>
      )}
      {busyStatus && (
        <div className="tailor-running" role="status">
          <LoaderCircle className="spin" size={18} />
          {state.status === "queued"
            ? "Waiting for a free tailoring slot (Settings → Jobs tailored at the same time)…"
            : state.action === "start"
              ? `Reading the job and picking your resume (${ENGINE_LABEL[state.engine] || "Claude"})…`
              : state.action === "answers"
                ? "Drafting application answers…"
                : state.action === "apply"
                  ? "Filling the application in Chrome…"
                  : "Working on your changes…"}
          {state.running_since && <span>{elapsedLabel(state.running_since)}</span>}
        </div>
      )}
      {state?.status === "failed" && (
        <div className="tailor-error">
          <p>Couldn’t finish: {state.error}</p>
          <button className="button secondary" disabled={locked} onClick={() => start(true)}>
            Try again
          </button>
        </div>
      )}
      <BlockedNotice turns={state?.turns} />
      {result && (
        <div className={`tailor-body ${busyStatus ? "is-busy" : ""}`}>
          <BlockerBanner result={result} />
          <p className="tailor-oneline">
            <strong>{BUCKETS[result.bucket] || result.bucket}</strong> resume ·{" "}
            {result.recommendation === "send as-is" ? "recommend sending as-is" : "recommend the tweaks"} ·{" "}
            <span className="muted">
              {ENGINE_LABEL[state.engine] || "Claude"}
              {state.fell_back ? " (Claude’s usage ran out)" : ""}
            </span>
          </p>
          <p className="tailor-reason">{result.recommendation_reason}</p>
          {state.turns?.[state.turns.length - 1]?.comment ? (
            <CommentReply turns={state.turns} message={result.message} />
          ) : (
            result.message && <p className="tailor-message">{result.message}</p>
          )}
          <Coverage coverage={state.coverage} />
          {!state.coverage && !busyStatus && (
            <p className="coverage-line muted">
              {(result.keywords?.present || []).some((k) => typeof k === "string")
                ? "No coverage score here: this resume was tailored before scores existed. Start over to get one."
                : "No coverage score here: the keyword check came back empty. Start over to run it again."}
            </p>
          )}
          <div className="tailor-grid">
            <ResumePreview slug={slug} version={state.updated} />
            <div className="tailor-side">
              <Checks build={state.build} />
              <h3>Tweaks</h3>
              {tweaks.length === 0 && <p className="muted">No tweaks suggested. The resume fits this job as it is.</p>}
              {tweaks.map((t) => (
                <TweakCard
                  key={t.id}
                  t={t}
                  choice={choices[t.id]}
                  onChoose={choose}
                  feedback={feedback[t.id]}
                  onFeedback={setFeedbackFor}
                  disabled={busyStatus}
                  coverage={state.coverage}
                />
              ))}
              {tweaks.length > 0 && (
                <div className="tweak-bar">
                  <button className="button" disabled={locked || !hasDecision(body)} onClick={() => decide(body)}>
                    Apply my choices
                  </button>
                  {tweaks.some((t) => t.status === "pending") && (
                    <button
                      className="button secondary"
                      disabled={locked}
                      onClick={() => decide({ approve: tweaks.filter((t) => t.status === "pending").map((t) => t.id) })}
                    >
                      Use all
                    </button>
                  )}
                  <button className="text-button" disabled={locked} onClick={() => decide({ as_is: true })}>
                    Send as-is
                  </button>
                </div>
              )}
            </div>
          </div>
          <ResumeComment
            resetKey={`${slug}|${state.updated}`}
            disabled={locked}
            onSend={(comment) => decide({ ...body, comment })}
          />
          <TailorDetails result={result} onRequest={(r) => decide({ request: r })} locked={locked} openBoost />
        </div>
      )}
    </section>
    <AnswersPanel slug={slug} state={state} onState={setState} />
    <ApplyPanel slug={slug} state={state} onState={setState} onChanged={onChanged} />
    </>
  );
}
// ── Application answers (step 12) ─────────────────────────────────
const answersBase = (slug) => `/api/jobs/${encodeURIComponent(slug)}/answers`;
function AnswerField({ q, value, onChange }) {
  const options = q.options?.length ? q.options : q.type === "boolean" ? ["Yes", "No"] : [];
  if (options.length && q.type === "multiselect") {
    const chosen = (value || "").split(" | ").filter(Boolean);
    const toggle = (o) => onChange((chosen.includes(o) ? chosen.filter((c) => c !== o) : [...chosen, o]).join(" | "));
    return (
      <div className="answer-checks">
        {options.map((o) => (
          <label key={o} className="check-label">
            <input type="checkbox" checked={chosen.includes(o)} onChange={() => toggle(o)} />
            {o}
          </label>
        ))}
      </div>
    );
  }
  if (options.length)
    return (
      <select className="answer-input" value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    );
  return q.type === "textarea" ? (
    <textarea className="answer-input" value={value || ""} onChange={(e) => onChange(e.target.value)} />
  ) : (
    <input
      className="answer-input"
      value={value || ""}
      placeholder={q.type === "multiselect" ? "Options separated by |" : ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
// Local choices on a job's answers until they're sent in one request
function useAnswerEdits(key) {
  const [fill, setFill] = useState({}),
    [edit, setEdit] = useState({}),
    [change, setChange] = useState({}),
    [open, setOpen] = useState({});
  useEffect(() => {
    setFill({});
    setEdit({});
    setChange({});
    setOpen({});
  }, [key]);
  return { fill, setFill, edit, setEdit, change, setChange, open, setOpen };
}
function answerBody(block, e, reviewed) {
  const items = block?.items || {};
  const approve = Object.entries(items)
    .filter(([id, it]) => it.status === "draft" && !(id in e.edit) && !(id in e.change))
    .map(([id]) => id);
  const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => String(v).trim()));
  return { approve, fill: clean(e.fill), edit: clean(e.edit), change: clean(e.change), reviewed };
}
function AnswerList({ block, e, disabled }) {
  const questions = Object.fromEntries((block.questions || []).map((q) => [q.id, q]));
  const entries = (block.questions || []).map((q) => [q.id, block.items?.[q.id]]).filter(([, it]) => it);
  const group = (test) => entries.filter(([, it]) => test(it));
  const needsYou = group((it) => it.status === "needs_you");
  const drafts = group((it) => it.kind === "written" && it.status !== "skipped");
  const facts = group((it) => ["fact", "you"].includes(it.kind) && it.status === "approved");
  const rest = group((it) => it.kind === "upload" || it.status === "skipped");
  const label = (q) => (
    <span className="answer-q">
      {q.label}
      {q.required && <b title="Required"> *</b>}
      {q.section === "eeo" && <em> voluntary</em>}
    </span>
  );
  return (
    <div className="answer-list">
      {needsYou.length > 0 && (
        <section>
          <h3>Needs you ({needsYou.length})</h3>
          {needsYou.map(([id, it]) => (
            <div key={id} className="answer-row needs-you">
              {label(questions[id])}
              <small>{it.reason}</small>
              {!disabled && (
                <AnswerField
                  q={questions[id]}
                  value={e.fill[id]}
                  onChange={(v) => e.setFill({ ...e.fill, [id]: v })}
                />
              )}
            </div>
          ))}
        </section>
      )}
      {drafts.length > 0 && (
        <section>
          <h3>Written answers</h3>
          {drafts.map(([id, it]) => (
            <div key={id} className={`answer-row written status-${it.status}`}>
              {label(questions[id])}
              {id in e.edit ? (
                <textarea
                  className="answer-input"
                  rows={it.letter ? 16 : undefined}
                  value={e.edit[id]}
                  onChange={(ev) => e.setEdit({ ...e.edit, [id]: ev.target.value })}
                />
              ) : (
                <p className="answer-text">{it.value}</p>
              )}
              <small>
                {it.status === "approved" ? "Approved" : "Draft"} · {it.value.split(/\s+/).filter(Boolean).length} words
                {it.reason ? ` · ${it.reason}` : ""}
                {it.letter ? " · approving it makes the cover letter file the form gets" : ""}
              </small>
              {!it.edited && (it.style || []).length > 0 && (
                <p className="tailor-warning">
                  Style check (your writing rules): {it.style.join(" · ")}. Edit it, or use Change… to have it rewritten.
                </p>
              )}
              {!disabled && (
                <div className="tweak-actions">
                  <button
                    className={`chip ${id in e.edit ? "on" : ""}`}
                    onClick={() => {
                      const next = { ...e.edit };
                      if (id in next) delete next[id];
                      else next[id] = it.value;
                      e.setEdit(next);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    className={`chip ${id in e.change ? "on" : ""}`}
                    onClick={() => {
                      const next = { ...e.change };
                      if (id in next) delete next[id];
                      else next[id] = "";
                      e.setChange(next);
                    }}
                  >
                    Change…
                  </button>
                </div>
              )}
              {id in e.change && (
                <textarea
                  className="tweak-feedback"
                  autoFocus
                  placeholder="What should change? e.g. shorter, mention their search product"
                  value={e.change[id]}
                  onChange={(ev) => e.setChange({ ...e.change, [id]: ev.target.value })}
                />
              )}
            </div>
          ))}
        </section>
      )}
      {facts.length > 0 && (
        <details className="answer-facts">
          <summary>From your profile ({facts.length})</summary>
          {facts.map(([id, it]) => (
            <div key={id} className="answer-fact">
              {label(questions[id])}
              {e.open[id] ? (
                <AnswerField q={questions[id]} value={e.edit[id] ?? it.value} onChange={(v) => e.setEdit({ ...e.edit, [id]: v })} />
              ) : (
                <span className="answer-value">{it.value}</span>
              )}
              {!disabled && !e.open[id] && (
                <button className="text-button" onClick={() => e.setOpen({ ...e.open, [id]: true })}>
                  Edit
                </button>
              )}
            </div>
          ))}
        </details>
      )}
      {rest.length > 0 && (
        <details className="answer-facts">
          <summary>Uploads and skipped ({rest.length})</summary>
          {rest.map(([id, it]) => (
            <div key={id} className="answer-fact">
              {label(questions[id])}
              <span className="answer-value muted">
                {it.kind === "upload" ? "Upload" : "Skipped"}: {it.reason}
              </span>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
function AnswersPanel({ slug, state, onState }) {
  const block = state?.answers;
  const e = useAnswerEdits(`${slug}|${block?.updated}`);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  if (!state || state.status === "none" || !state.result) return null;
  async function send(path, body) {
    setBusy(true);
    setError("");
    try {
      onState(await api(path, body));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const working = ["queued", "running"].includes(block?.status);
  const body = block?.status === "ready" ? answerBody(block, e, true) : null;
  const pendingChanges =
    body && (body.approve.length || Object.keys(body.fill).length || Object.keys(body.edit).length || Object.keys(body.change).length);
  return (
    <section className="surface tailor-panel answers-panel" aria-label="Application answers">
      <div className="section-title">
        <h2>Application answers</h2>
        {["ready", "none", "failed"].includes(block?.status) && (
          <button className="text-button" disabled={busy} onClick={() => send(answersBase(slug), { restart: true })}>
            <RefreshCw size={14} />
            {block.status === "none" ? "Check the form again" : "Redo answers"}
          </button>
        )}
      </div>
      {error && <p className="tailor-error">{error}</p>}
      {!block && (
        <div className="tailor-empty">
          <p>
            Reads this job’s application form and drafts answers: facts from your profile, written
            answers in your voice for you to approve, and anything only you can answer (like salary)
            set aside for you. Works when the site shows its questions ahead of time (Greenhouse, Ashby).
          </p>
          <button className="button secondary" disabled={busy || state.status === "running"} onClick={() => send(answersBase(slug), {})}>
            <Sparkles size={16} />
            Prepare answers
          </button>
        </div>
      )}
      {working && (
        <div className="tailor-running" role="status">
          <LoaderCircle className="spin" size={18} />
          {block.status === "queued" ? "Waiting for a free slot…" : "Reading the form and drafting answers…"}
        </div>
      )}
      {block?.status === "none" && (
        <p className="muted answer-note">
          This site doesn’t show its questions before you apply (Workday, Lever and most company sites). The
          apply agent will ask you when it reaches a question it can’t answer from your profile.
        </p>
      )}
      {block?.status === "failed" && <p className="tailor-error">Couldn’t draft answers: {block.error}</p>}
      {block?.status === "ready" && (
        <>
          {block.message && <p className="tailor-message">{block.message}</p>}
          <AnswerList block={block} e={e} disabled={busy} />
          <div className="tweak-bar">
            <button className="button" disabled={busy || !pendingChanges} onClick={() => send(`${answersBase(slug)}/decide`, body)}>
              Save answers
            </button>
            <span className="muted small">Drafts you haven’t edited are approved as they are.</span>
          </div>
        </>
      )}
    </section>
  );
}
// ── Filling the application (step 13) ─────────────────────────────
const applyBase = (slug) => `/api/jobs/${encodeURIComponent(slug)}/apply`;
const APPLY_LABEL = {
  queued: "Waiting for a free fill slot (Settings → Forms filled at the same time)…",
  running: "Filling the form in your Chrome…",
  ready_to_submit: "Filled. Check the tab in Chrome, then submit",
  needs_you: "Filled what it could. A few fields need you",
  blocked: "Stopped: needs you in Chrome",
  submitted: "Submitted",
  failed: "Couldn’t fill the form",
};
const CODEX_FILL_WARNING =
  "Codex fills through a browser console that runs code. Unlike Claude, nothing enforces its limits (stay on the application site, upload only your resume); it's only asked to follow them, and an audit flags anything it ran that breaks them. Fill with Codex?";
// A form question the fill couldn't answer: several choices ("Select 2") get checkboxes
const MULTI_TYPES = ["multiselect", "checkbox", "checkboxes", "multi_select"];
const fieldFor = (u) => ({
  type:
    u.type === "textarea"
      ? "textarea"
      : u.options?.length && (MULTI_TYPES.includes(u.type) || /\b(select|choose|pick) (two|three|\d+|all|up to)\b/i.test(u.label))
        ? "multiselect"
        : u.options?.length
          ? "select"
          : "text",
  options: u.options,
});
function ApplyPanel({ slug, state, onState, onChanged, embedded = false, shortcuts = false }) {
  const block = state?.apply;
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [fill, setFill] = useState({}),
    [engine, setEngine] = useState("claude");
  useEffect(() => setFill({}), [block?.updated]);
  const working = ["queued", "running"].includes(block?.status);
  const canMarkApplied = block && !working && block.status !== "submitted";
  const hasFill = Object.values(fill).some((v) => String(v).trim());
  // Forms page: Enter (⌘Enter while typing) fills your answers in, s submits, m marks it submitted
  useEffect(() => {
    if (!shortcuts || !block) return;
    const keys = (e) => {
      if (busy || working || e.defaultPrevented) return;  // ⌘↵ in the comment box sends the comment
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && hasFill) {
        e.preventDefault();
        fillThese();
        return;
      }
      if (e.target.closest("input,textarea,select,dialog,[contenteditable]") || e.metaKey || e.ctrlKey || e.altKey)
        return;
      const k = e.key.toLowerCase();
      if (k === "enter" && hasFill) fillThese();
      else if (k === "s" && block.status === "ready_to_submit") submitForMe();
      else if (k === "m" && canMarkApplied) {
        if (confirm("Mark this application as submitted? The job moves to Applied.")) markApplied();
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  });
  useEffect(() => {
    api("/api/tailor/settings")
      .then((st) => setEngine(st.fill_engine || "claude"))
      .catch(() => {});
  }, []);
  const startFill = () => {
    if (engine === "codex" && !confirm(CODEX_FILL_WARNING)) return;
    send(applyBase(slug), { engine });
  };
  const engineMenu = (
    <label className="fill-engine">
      Fill with
      <select value={engine} onChange={(e) => setEngine(e.target.value)} disabled={busy}>
        <option value="claude">Claude (Sonnet, enforced limits)</option>
        <option value="codex">Codex (limits not enforced)</option>
      </select>
    </label>
  );
  if (!state?.result) return null;
  async function send(path, body = {}) {
    setBusy(true);
    setError("");
    try {
      onState(await api(path, body));
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function markApplied() {
    send(`${applyBase(slug)}/submitted`);
  }
  function fillThese() {
    send(`${applyBase(slug)}/continue`, { answers: fill });
  }
  function submitForMe() {
    if (confirm("Submit this application now? Claude will click the final Submit button on the filled form in Chrome. Check the tab first."))
      send(`${applyBase(slug)}/submit`);
  }
  const unanswered = block?.unanswered || [];
  return (
    <section className={embedded ? "apply-panel embedded" : "surface tailor-panel apply-panel"} aria-label="Application">
      <div className="section-title">
        <h2>Application</h2>
        {block && !working && block.status !== "submitted" && (
          <span className="fill-again">
            {engineMenu}
            <button className="text-button" disabled={busy} onClick={startFill}>
              <RefreshCw size={14} />
              Fill again
            </button>
          </span>
        )}
      </div>
      {error && <p className="tailor-error">{error}</p>}
      {!block && (
        <div className="tailor-empty">
          <p>
            Opens this job’s application in your Chrome (with the Claude extension connected) and fills it with
            your tailored resume, approved answers and profile. It stops before Submit and leaves the tab open
            for you to check. It never signs in, solves CAPTCHAs or ticks consent boxes.
          </p>
          <div className="tweak-bar">
            <button className="button" disabled={busy || state.status === "running"} onClick={startFill}>
              <Sparkles size={16} />
              Fill application
            </button>
            {engineMenu}
          </div>
          {engine === "codex" && <p className="tailor-warning">{CODEX_FILL_WARNING.replace(" Fill with Codex?", "")}</p>}
        </div>
      )}
      {block && (
        <>
          <div className={working ? "tailor-running" : block.status === "submitted" ? "apply-done" : "apply-status"} role="status">
            {working && <LoaderCircle className="spin" size={18} />}
            {block.status === "submitted" && <CircleCheck size={18} />}
            <strong>
              {block.status === "submitted" && block.submitted_by === "owner"
                ? "Submitted by you · marked Applied"
                : block.status === "submitted"
                  ? "Submitted · marked Applied"
                  : APPLY_LABEL[block.status] || block.status}
            </strong>
            {block.submitted_by !== "owner" && (
              <span className="muted small">{block.engine === "codex" ? "Codex" : "Claude"}</span>
            )}
          </div>
          {block.error && <p className="tailor-error">{block.error}</p>}
          {block.message && !working &&
            (block.turns?.[block.turns.length - 1]?.comment ? (
              <CommentReply turns={block.turns} message={block.message} />
            ) : (
              <p className="tailor-message">{block.message}</p>
            ))}
          <BlockedNotice turns={block.turns} audited={block.engine === "codex"} />
          {block.status === "blocked" && !working && (
            <div className="tweak-bar">
              <button className="button" disabled={busy} onClick={() => send(`${applyBase(slug)}/continue`, { signed_in: true })}>
                I signed in: continue
              </button>
              <span className="muted small">Sign in on that site in Chrome first. The fill carries on in its own tab.</span>
            </div>
          )}
          {!working && unanswered.length > 0 && (
            <div className="answer-list">
              <section>
                <h3>The form needs you ({unanswered.length})</h3>
                {unanswered.map((u) => (
                  <div key={u.label} className="answer-row needs-you">
                    <span className="answer-q">
                      {u.label}
                      {u.required && <b title="Required"> *</b>}
                    </span>
                    <small>{u.reason}</small>
                    <AnswerField
                      q={fieldFor(u)}
                      value={fill[u.label]}
                      onChange={(v) => setFill({ ...fill, [u.label]: v })}
                    />
                  </div>
                ))}
              </section>
              <div className="tweak-bar">
                <button className="button" disabled={busy || !hasFill} onClick={fillThese}>
                  Fill these in
                  {shortcuts && <kbd>Enter</kbd>}
                </button>
                <span className="muted small">Leave a field empty to fill it yourself in Chrome.</span>
              </div>
            </div>
          )}
          {canMarkApplied && (
            <div className="tweak-bar">
              {block.status === "ready_to_submit" && (
                <button className="button" disabled={busy} onClick={submitForMe}>
                  Submit for me
                  {shortcuts && <kbd>s</kbd>}
                </button>
              )}
              <button className="button secondary" disabled={busy} onClick={markApplied}>
                {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}
                I submitted it myself
                {shortcuts && <kbd>m</kbd>}
              </button>
            </div>
          )}
          {!working && ["needs_you", "ready_to_submit", "blocked"].includes(block.status) && (
            <ResumeComment
              resetKey={`${slug}|apply|${block.updated}`}
              disabled={busy}
              label="Comment on the filled form"
              placeholder="Ask for a change, e.g. “Replace the incident answer with: …” or “Set race to Decline to self-identify”"
              hint="Goes to the session that filled this form. It changes the open tab and stops before Submit; text you give for an answer is kept for Fill again. ⌘↵ sends."
              onSend={(comment) => send(`${applyBase(slug)}/comment`, { comment })}
            />
          )}
          {(block.filled || []).length > 0 && (
            <details className="answer-facts">
              <summary>Filled fields ({block.filled.length})</summary>
              {block.filled.map((f, i) => (
                <div key={i} className="answer-fact">
                  <span className="answer-q">{f.label}</span>
                  <span className="answer-value">{f.value}</span>
                  <span className="muted small">{f.source}</span>
                </div>
              ))}
            </details>
          )}
          {!working && (
            <a className="text-link apply-record" href={`/view/${encodeURIComponent(slug)}/application.md`} target="_blank" rel="noreferrer">
              Application record <ArrowUpRight size={12} />
            </a>
          )}
        </>
      )}
    </section>
  );
}
// ── Forms: every application Claude filled, one at a time ────────
const FORM_GROUPS = {
  needs_you: "Form needs you",
  ready_to_submit: "Ready to submit",
  blocked: "Stopped: needs you in Chrome",
  failed: "Couldn’t fill",
};
const fillOf = (job) => job.artifacts?.tailor?.apply;
// Forms waiting on you, in the order to work through them (newest first within each group).
// Only jobs still Not Applied: one you marked Applied, Ignore, Reject or later is done with.
function formQueue(jobs) {
  const order = Object.keys(FORM_GROUPS);
  return (jobs || [])
    .filter((j) => j.status === "Not Applied" && order.includes(fillOf(j)))
    .sort((a, b) => order.indexOf(fillOf(a)) - order.indexOf(fillOf(b)));
}
function FormsPage({ jobs, slug, onJobsChanged }) {
  const [q, setQ] = useSaved("loom-forms-q"),
    [only, setOnly] = useSaved("loom-forms-only"),
    [source, setSource] = useSaved("loom-forms-source");
  const all = formQueue(jobs);
  const items = all.filter((j) => (!only || fillOf(j) === only) && fromSource(j, source) && matchesText(j, q));
  const filling = (jobs || []).filter((j) => ["queued", "running"].includes(fillOf(j)));
  const [index, setIndex] = useState(0);
  // The route names the job you're on; once it's submitted, the next one takes its place
  const found = slug ? items.findIndex((j) => j.slug === slug) : -1;
  const pos = found >= 0 ? found : Math.min(index, Math.max(0, items.length - 1));
  const item = items[pos];
  useEffect(() => {
    if (found >= 0 && found !== index) setIndex(found);
  });
  const go = (n) => {
    const next = items[Math.min(Math.max(n, 0), items.length - 1)];
    if (next && next !== item) location.hash = `forms/${encodeURIComponent(next.slug)}`;
  };
  const [state, setState] = useState(null),
    [error, setError] = useState("");
  const showing = useRef(null);
  showing.current = item?.slug;
  const load = (s = item?.slug) =>
    s &&
    api(tailorBase(s))
      .then((next) => {
        if (showing.current !== s) return;
        setState((prev) => {
          if (["queued", "running"].includes(prev?.apply?.status) && !["queued", "running"].includes(next.apply?.status))
            onJobsChanged?.();
          return next;
        });
      })
      .catch((e) => showing.current === s && setError(e.message));
  useEffect(() => {
    setState(null);
    setError("");
    load();
  }, [item?.slug]);
  const working = ["queued", "running"].includes(state?.apply?.status);
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => load(), 3000);
    return () => clearInterval(t);
  }, [working, item?.slug]);
  useEffect(() => {
    const keys = (e) => {
      if (e.target.closest("input,textarea,select,dialog,[contenteditable]") || e.metaKey || e.ctrlKey || e.altKey)
        return;
      const k = e.key.toLowerCase();
      if (k === "j") go(pos + 1);
      else if (k === "k") go(pos - 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  });
  const groups = Object.entries(FORM_GROUPS)
    .map(([status, label]) => [status, label, all.filter((j) => fillOf(j) === status).length])
    .filter(([, , n]) => n);
  const running = filling.filter((j) => fillOf(j) === "running").length;
  return (
    <>
      <div className="section-title review-title">
        <h2>
          Forms <span className="count-pill">{jobs ? items.length : "…"}</span>
        </h2>
        <span className="review-status">
          {filling.length > 0 && (
            <>
              <LoaderCircle className="spin" size={13} /> Filling {running}
              {filling.length - running ? ` · ${filling.length - running} queued` : ""}
            </>
          )}
        </span>
      </div>
      <p className="muted review-intro">
        Applications filled in your Chrome. Answer what the form still needs, check the tab, then submit. Each one leaves
        this list once it’s submitted.
      </p>
      {all.length > 0 && (
        <div className="queue-filters">
          <div className="queue-row">
            <label className="search">
              <Search size={18} />
              <input
                aria-label="Search forms"
                type="search"
                placeholder="Search roles, companies, locations…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </label>
            <SourceSelect jobs={all} value={source} onChange={setSource} />
          </div>
          <div className="forms-groups" aria-label="Show forms that are">
            <button className={`tag neutral ${!only ? "active" : ""}`} onClick={() => setOnly("")}>
              All · {all.length}
            </button>
            {groups.map(([status, label, n]) => (
              <button
                key={status}
                className={`tag ${status === "ready_to_submit" ? "soft" : "warning"} ${only === status ? "active" : ""}`}
                onClick={() => setOnly(only === status ? "" : status)}
                aria-pressed={only === status}
              >
                {label} · {n}
              </button>
            ))}
          </div>
        </div>
      )}
      {jobs === null ? (
        <Loading />
      ) : !item && all.length > 0 ? (
        <Empty title="Nothing matches these filters" text="Clear them to see every form waiting on you." icon={FileCheck2}>
          <button
            className="button secondary"
            onClick={() => {
              setQ("");
              setOnly("");
              setSource("");
            }}
          >
            Clear filters
          </button>
        </Empty>
      ) : !item ? (
        <Empty
          title={filling.length ? "Forms are being filled" : "No forms waiting on you"}
          text={
            filling.length
              ? `${filling.length} application${filling.length === 1 ? " is" : "s are"} filling in Chrome. ${filling.length === 1 ? "It" : "They"}’ll show up here when ready to check.`
              : "Fill applications from My jobs (Select all ready to fill) or from Review. Each filled form lands here to check and submit."
          }
          icon={FileCheck2}
        />
      ) : (
        <section className="surface review-card forms-card" key={item.slug} aria-label={`${item.company} ${item.title}`}>
          <div className="review-head">
            <div>
              <div className="eyebrow">
                {item.company} · {pos + 1} of {items.length}
              </div>
              <h1>
                <a href={`#job/${encodeURIComponent(item.slug)}`}>{item.title}</a>
              </h1>
              <div className="location">
                <MapPin size={14} />
                {item.location || "Location not specified"}
              </div>
              <div className="forms-links">
                <FileLinks job={item} />
                {(safeURL(item.url) || safeURL(item.apply_url)) && (
                  <External href={safeURL(item.url) || item.apply_url} className="text-link">
                    Posting
                  </External>
                )}
              </div>
            </div>
            <div className="review-nav">
              <IconButton label="Previous form (k)" disabled={pos === 0} onClick={() => go(pos - 1)}>
                <ArrowLeft size={16} />
              </IconButton>
              <IconButton label="Next form (j)" disabled={pos >= items.length - 1} onClick={() => go(pos + 1)}>
                <ArrowRight size={16} />
              </IconButton>
            </div>
          </div>
          {error ? (
            <p className="tailor-error">{error}</p>
          ) : !state ? (
            <Loading />
          ) : (
            <ApplyPanel slug={item.slug} state={state} onState={setState} onChanged={onJobsChanged} embedded shortcuts />
          )}
          <p className="keyboard-hint review-keys">
            <kbd>Enter</kbd> fill your answers in (<kbd>⌘</kbd>
            <kbd>Enter</kbd> while typing) · <kbd>s</kbd> submit for me · <kbd>m</kbd> I submitted it ·{" "}
            <kbd>j</kbd>/<kbd>k</kbd> next/previous
          </p>
        </section>
      )}
    </>
  );
}
function SettingRow({ title, text, children }) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p className="muted small">{text}</p>
      </div>
      <div className="setting-control">{children}</div>
    </div>
  );
}
function SettingsPage() {
  const [settings, setSettings] = useState(null),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  useEffect(() => {
    api("/api/tailor/settings")
      .then(setSettings)
      .catch((e) => setError(e.message));
  }, []);
  async function change(update) {
    setError("");
    try {
      setSettings(await api("/api/tailor/settings", update));
      setSaved("Saved");
      setTimeout(() => setSaved(""), 1500);
    } catch (e) {
      setError(e.message);
    }
  }
  const toggle = (key) => (
    <input type="checkbox" checked={settings[key] !== false} onChange={(e) => change({ [key]: e.target.checked })} />
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">HOW LOOM WORKS FOR YOU</div>
          <h1>Settings</h1>
          <p>What happens after you keep a job, and how forms get filled.</p>
        </div>
        {saved && <span className="tag success">{saved}</span>}
      </div>
      {error && <div className="warning-box">{error}</div>}
      {!settings ? (
        !error && <Loading />
      ) : (
        <div className="settings-page">
          <section className="surface">
            <div className="section-title">
              <h2>Tailoring</h2>
            </div>
            <SettingRow title="Tailor jobs as I keep them" text="A kept job gets its resume picked and tailored in the background.">
              {toggle("auto_tailor")}
            </SettingRow>
            <SettingRow title="Tailor with" text="Each job gets its own session with this model.">
              <select value={settings.engine} onChange={(e) => change({ engine: e.target.value })}>
                <option value="claude">Claude (Opus)</option>
                <option value="codex">Codex (5.6 sol, extra high)</option>
              </select>
            </SettingRow>
            {settings.engine === "claude" && (
              <SettingRow title="Use Codex if Claude runs out" text="A job whose first turn hits Claude's usage limit starts over with Codex.">
                {toggle("fallback")}
              </SettingRow>
            )}
            <SettingRow
              title="Jobs tailored at the same time"
              text="Each is its own session. More at once clears a backlog faster and uses your usage faster."
            >
              <select value={settings.parallel || 2} onChange={(e) => change({ parallel: Number(e.target.value) })}>
                {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </SettingRow>
          </section>
          <section className="surface">
            <div className="section-title">
              <h2>Review</h2>
            </div>
            <SettingRow
              title="Skip Review"
              text="Tweaks and answers are used as drafted; you check everything in the filled form before Submit. Jobs you keep with Keep & review myself still stop in Review."
            >
              {toggle("auto_review")}
            </SettingRow>
            <SettingRow title="Draft application answers" text="After the resume, read the form's questions and draft the answers.">
              {toggle("auto_answers")}
            </SettingRow>
          </section>
          <section className="surface">
            <div className="section-title">
              <h2>Filling forms</h2>
            </div>
            <SettingRow title="Fill forms with" text="Claude runs with enforced limits on sites and uploads. Codex's limits are instructions only.">
              <select
                value={settings.fill_engine || "claude"}
                onChange={(e) => {
                  if (e.target.value === "codex" && !confirm(CODEX_FILL_WARNING)) return;
                  change({ fill_engine: e.target.value });
                }}
              >
                <option value="claude">Claude (Sonnet)</option>
                <option value="codex">Codex (limits not enforced)</option>
              </select>
            </SettingRow>
            <SettingRow
              title="Forms filled at the same time"
              text="Each fill works in its own tab of your Chrome. If two fills get in each other's way, set it back to 1. Fill these in, Submit for me and I signed in start right away and don't wait for a slot."
            >
              <select value={settings.fill_parallel || 1} onChange={(e) => change({ fill_parallel: Number(e.target.value) })}>
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </SettingRow>
          </section>
          <NotificationSettings />
          <VouchedSkills />
        </div>
      )}
    </>
  );
}
function VouchedSkills() {
  const [skills, setSkills] = useState(null),
    [note, setNote] = useState("");
  useEffect(() => {
    api("/api/vouched")
      .then((d) => setSkills(d.skills))
      .catch((e) => setNote(e.message));
  }, []);
  async function remove(skill) {
    try {
      setSkills((await api("/api/vouched/remove", { skill })).skills);
    } catch (e) {
      setNote(e.message);
    }
  }
  if (!skills) return note ? <div className="warning-box">{note}</div> : null;
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Skills you’ve confirmed</h2>
      </div>
      <p className="muted small">
        When you tell a tailoring session you have a skill that cv.md doesn’t mention, it’s added and remembered here,
        and every later resume can use it. Remove one to stop that. Adding a line about it to cv.md is still worth it
        for interviews.
      </p>
      {skills.length === 0 ? (
        <p className="muted small">None yet.</p>
      ) : (
        <div className="chip-row">
          {skills.map((s) => (
            <span key={s.skill} className="tag neutral vouched-skill" title={`Confirmed ${s.added}${s.job ? ` on ${s.job}` : ""}`}>
              {s.skill}
              <button className="icon-x" aria-label={`Remove ${s.skill}`} onClick={() => remove(s.skill)}>
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      {note && <p className="muted small">{note}</p>}
    </section>
  );
}
function NotificationSettings() {
  const [cfg, setCfg] = useState(null),
    [note, setNote] = useState("");
  useEffect(() => {
    api("/api/notify")
      .then(setCfg)
      .catch((e) => setNote(e.message));
  }, []);
  async function change(update) {
    try {
      setCfg(await api("/api/notify", update));
    } catch (e) {
      setNote(e.message);
    }
  }
  async function test() {
    setNote("Sending…");
    try {
      const res = await api("/api/notify/test", {});
      setNote(res.ok ? "Sent. Check your phone and this Mac." : `Problems: ${res.errors.join("; ")}`);
    } catch (e) {
      setNote(e.message);
    }
  }
  if (!cfg) return note ? <div className="warning-box">{note}</div> : null;
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Notifications</h2>
        <button className="text-button" onClick={test}>
          Send a test
        </button>
      </div>
      <p className="muted small">
        When a filled form is ready to submit, needs your answers, or stops or fails. Each one links to the job.
      </p>
      <SettingRow
        title="Phone (ntfy)"
        text={
          <>
            Install the free ntfy app, tap +, and subscribe to <code className="notify-topic">{cfg.topic}</code> on
            ntfy.sh. Keep it private: anyone with this name can read the notifications.
          </>
        }
      >
        <input type="checkbox" checked={cfg.phone} onChange={(e) => change({ phone: e.target.checked })} />
      </SettingRow>
      <SettingRow title="Mac banner" text="A macOS notification on this Mac.">
        <input type="checkbox" checked={cfg.mac} onChange={(e) => change({ mac: e.target.checked })} />
      </SettingRow>
      {note && <p className="muted small">{note}</p>}
    </section>
  );
}
// What happened to a job that went through Skip Review, in one line
function skippedSummary(item) {
  const t = item.tailor || {};
  const tweaks = t.result?.tweaks || [];
  const used = tweaks.filter((x) => x.status === "applied").length;
  const waiting = tweaks.filter((x) => x.status === "pending").length;
  const answers = Object.values(t.answers?.items || {});
  const autoAnswers = answers.filter((a) => a.auto && a.status === "approved").length;
  const fill = t.apply?.status;
  return [
    tweaks.length === 0 ? "no tweaks needed" : used ? `${used} tweak${used > 1 ? "s" : ""} used automatically` : "",
    waiting ? `${waiting} tweak${waiting > 1 ? "s" : ""} waiting for you` : "",
    autoAnswers ? `${autoAnswers} answer${autoAnswers > 1 ? "s" : ""} approved automatically` : "",
    fill ? (fill === "submitted" ? "submitted" : (APPLY_LABEL[fill] || fill).toLowerCase()) : "",
    item.job_status && item.job_status !== "Not Applied" ? item.job_status : "",
  ]
    .filter(Boolean)
    .join(" · ")
    .replace(/^./, (c) => c.toUpperCase());
}
const REVIEW_KINDS = { resume: "Resumes", answers: "Answers", auto: "Quick look" };
function ReviewPage({ review, reload, notify }) {
  const items = review?.items || [];
  const counts = review?.counts || {};
  const [index, setIndex] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [gone, setGone] = useState(() => new Set());
  const [q, setQ] = useSaved("loom-review-q"),
    [kind, setKind] = useSaved("loom-review-kind"),
    [bucket, setBucket] = useSaved("loom-review-bucket"),
    [source, setSource] = useSaved("loom-review-source");
  const left = items.filter((i) => !gone.has(i.slug) && !gone.has(`${i.slug}|${i.type}`));
  const visible = left.filter(
    (i) =>
      (!kind || i.type === kind) &&
      (!bucket || i.tailor?.result?.bucket === bucket) &&
      fromSource(i, source) &&
      matchesText(i, q),
  );
  const filtering = Boolean(q.trim() || kind || bucket || source);
  const clearFilters = () => {
    setQ("");
    setKind("");
    setBucket("");
    setSource("");
  };
  // Stay on the job you're looking at when the list refreshes; if it's gone, the one now in its place
  const keyOf = (i) => `${i.slug}|${i.type}`;
  const current = useRef(null);
  if (current.current === null) {
    try {
      current.current = sessionStorage.getItem("loom-review-at");  // where you were before a refresh
    } catch {}
  }
  const found = current.current ? visible.findIndex((i) => keyOf(i) === current.current) : -1;
  const pos = found >= 0 ? found : Math.min(index, Math.max(0, visible.length - 1));
  const item = visible[pos];
  if (item) current.current = keyOf(item);
  useEffect(() => {
    try {
      if (item) sessionStorage.setItem("loom-review-at", keyOf(item));
    } catch {}
  });
  useEffect(() => {
    if (found >= 0 && found !== index) setIndex(found);  // so a finished job is replaced by the next one in place
  });
  const go = (n) => {
    const next = visible[Math.min(Math.max(n, 0), visible.length - 1)];
    if (!next) return;
    current.current = keyOf(next);
    setIndex(visible.indexOf(next));
  };
  const [fresh, setFresh] = useState({});  // the state an in-place action returned, until the list catches up
  const listed = item?.tailor;
  const state =
    item && fresh[item.slug] && (fresh[item.slug].updated || "") >= (listed?.updated || "") ? fresh[item.slug] : listed;
  const jobWorking = item?.working || ["queued", "running"].includes(state?.status);
  const result = state?.result;
  const tweaks = result?.tweaks || [];
  const pending = tweaks.filter((t) => t.status === "pending");
  const { choices, feedback, choose, setFeedbackFor } = useChoices(`${item?.slug}|${state?.updated}`);
  const isAnswers = item?.type === "answers";
  const isAuto = item?.type === "auto";  // went through on its own (Skip Review): here for a quick look
  const answerEdits = useAnswerEdits(`${item?.slug}|${item?.type}|${state?.answers?.updated}`);
  useEffect(() => {
    setGone(new Set());
  }, [review]);
  async function act(body, message) {
    if (!item || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await api(`${tailorBase(item.slug)}/decide`, { ...body, reviewed: true });
      setGone((prev) => new Set(prev).add(item.slug));
      notify?.(
        next.status === "running"
          ? `${item.company}: working on your change; it’ll come back here`
          : message || `${item.company}: done`,
      );
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  // Use/Skip, Use all, Send as-is, Undo: applied right away, and you stay on this job
  async function apply(body, message) {
    if (!item || busy || jobWorking) return;
    setBusy(true);
    setError("");
    try {
      const next = await api(`${tailorBase(item.slug)}/decide`, body);
      setFresh((prev) => ({ ...prev, [item.slug]: next }));
      notify?.(
        ["queued", "running"].includes(next.status)
          ? `${item.company}: working on it; it updates here`
          : message || `${item.company}: applied`,
      );
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const done = () =>
    isAnswers
      ? answersDone()
      : isAuto
        ? act({ ...decisionBody(choices, feedback), glanced: true }, `${item?.company}: looks good`)
        : act(decisionBody(choices, feedback), `${item?.company}: resume ready`);
  async function answersDone(fillAfter = false) {
    if (!item || busy) return;
    setBusy(true);
    setError("");
    try {
      const block = state.answers;
      const next = await api(`${answersBase(item.slug)}/decide`, answerBody(block, answerEdits, true));
      if (fillAfter) await api(applyBase(item.slug), {});
      setGone((prev) => new Set(prev).add(`${item.slug}|answers`));
      notify?.(
        next.answers?.status === "running"
          ? `${item.company}: rewriting an answer; it’ll come back here`
          : fillAfter
            ? `${item.company}: answers saved; filling the application in Chrome`
            : `${item.company}: answers saved`,
      );
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const useAll = () => pending.length && apply({ approve: pending.map((t) => t.id) }, `${item?.company}: tweaks used`);
  const applyChoices = () => {
    const body = decisionBody(choices, feedback);
    if (hasDecision(body)) apply(body, `${item?.company}: choices applied`);
  };
  const fillStatus = state?.apply?.status;
  const canFill = isAuto && (!fillStatus || ["failed", "blocked"].includes(fillStatus));
  async function fillApp() {
    if (!item || busy || !canFill) return;
    const body = decisionBody(choices, feedback);
    if (Object.keys(body.change).length) {
      setError("A Change… needs the session first. Send it, then fill when it’s back.");
      return;
    }
    if (review?.settings?.fill_engine === "codex" && !confirm(CODEX_FILL_WARNING)) return;
    setBusy(true);
    setError("");
    try {
      await api(`${tailorBase(item.slug)}/decide`, { ...body, glanced: true });  // Undo picked goes in first
      await api(applyBase(item.slug), {});
      setGone((prev) => new Set(prev).add(item.slug));
      notify?.(`${item.company}: filling the application in Chrome`);
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const asIs = () => apply({ as_is: true }, `${item?.company}: back to the bucket resume`);
  async function retry() {
    setBusy(true);
    try {
      await api(tailorBase(item.slug), { restart: true });
      setGone((prev) => new Set(prev).add(item.slug));
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function tailorWaiting() {
    if (!confirm(`Tailor ${counts.waiting} saved job${counts.waiting === 1 ? "" : "s"} that don’t have a resume yet?`))
      return;
    try {
      const res = await api("/api/tailor/queue", { all_waiting: true });
      notify?.(`${res.queued.length} job${res.queued.length === 1 ? "" : "s"} queued for tailoring`);
      reload();
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    const keys = (e) => {
      if (e.target.closest("input,textarea,select,dialog,[contenteditable]") || e.metaKey || e.ctrlKey || e.altKey)
        return;
      if (!item) return;
      const k = e.key.toLowerCase();
      if (k === "j") go(pos + 1);
      else if (k === "k") go(pos - 1);
      else if (isAnswers && (k === "enter" || k === "y")) answersDone();
      else if (isAnswers && k === "f") answersDone(true);
      else if (isAnswers) return;
      else if (!result || jobWorking) return;
      else if (k === "y") useAll();
      else if (k === "n") asIs();
      else if (k === "f" && canFill) fillApp();
      else if (k === "enter" || k === "d") done();
      else if (k === "o") window.open(resumeFile(item.slug, "Manas_Dalvi_Resume.pdf", state.updated), "_blank");
      else if (k === "a" && safeURL(item.apply_url || item.url)) window.open(item.apply_url || item.url, "_blank");
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  });
  const working = (counts.running || 0) + (counts.queued || 0);
  return (
    <>
      <div className="section-title review-title">
        <h2>
          Review <span className="count-pill">{review ? visible.length : "…"}</span>
        </h2>
        <span className="review-status">
          {working > 0 && (
            <>
              <LoaderCircle className="spin" size={13} /> Tailoring {counts.running || 0}
              {counts.queued ? ` · ${counts.queued} queued` : ""}
            </>
          )}
        </span>
      </div>
      <p className="muted review-intro">
        Tailored resumes waiting for a quick look. Pick Use or Skip on each tweak and press Done, or
        use all tweaks, or send the resume as it is. Each decision takes a few seconds; the next job
        is ready right away.
      </p>
      <a className="text-button review-settings-link" href="#settings">
        <SlidersHorizontal size={14} />
        Settings
      </a>
      {counts.waiting > 0 && (
        <div className="review-waiting">
          <span>
            {counts.waiting} saved job{counts.waiting === 1 ? "" : "s"} you haven’t applied to{" "}
            {counts.waiting === 1 ? "doesn’t" : "don’t"} have a resume yet.
          </span>
          <button className="button secondary" onClick={tailorWaiting}>
            <Sparkles size={15} />
            Tailor {counts.waiting === 1 ? "it" : "them"}
          </button>
        </div>
      )}
      {error && <p className="tailor-error">{error}</p>}
      {left.length > 0 && (
        <div className="queue-filters">
          <div className="queue-row">
            <label className="search">
              <Search size={18} />
              <input
                aria-label="Search review"
                type="search"
                placeholder="Search roles, companies, locations…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </label>
            <SourceSelect jobs={left} value={source} onChange={setSource} />
          </div>
          <div className="bucket-tabs" aria-label="What to review">
            <button className={!kind ? "active" : ""} onClick={() => setKind("")}>
              Everything · {left.length}
            </button>
            {Object.entries(REVIEW_KINDS).map(([key, label]) => {
              const n = left.filter((i) => i.type === key).length;
              return n ? (
                <button key={key} className={kind === key ? "active" : ""} onClick={() => setKind(key)}>
                  {label} · {n}
                </button>
              ) : null;
            })}
          </div>
          <div className="bucket-tabs" aria-label="Resume categories">
            <button className={!bucket ? "active" : ""} onClick={() => setBucket("")}>
              All roles
            </button>
            {Object.entries(BUCKETS).map(([key, label]) => (
              <button key={key} className={bucket === key ? "active" : ""} onClick={() => setBucket(key)}>
                {key === "generalist" ? "Software" : key === "mle" ? "ML" : label}
              </button>
            ))}
          </div>
        </div>
      )}
      {review === null ? (
        <Loading />
      ) : !item && filtering && left.length > 0 ? (
        <Empty title="Nothing matches these filters" text="Clear them to see everything waiting for review." icon={ClipboardCheck}>
          <button className="button secondary" onClick={clearFilters}>
            Clear filters
          </button>
        </Empty>
      ) : !item ? (
        <Empty
          title={working ? "Resumes are on the way" : "Nothing to review"}
          text={
            working
              ? `${working} job${working === 1 ? " is" : "s are"} being tailored. They’ll show up here when ready.`
              : "Keep jobs from your inbox and their resumes will be tailored and land here."
          }
          icon={ClipboardCheck}
        />
      ) : (
        <section className="surface review-card" key={`${item.slug}|${item.type}`} aria-label={`${item.company} ${item.title}`}>
          <div className="review-head">
            <div>
              <div className="eyebrow">
                {item.company} · {pos + 1} of {visible.length}
              </div>
              {isAuto && (
                <div className="review-skipped">
                  <span className="tag neutral">Skipped review</span>
                  <span className="muted small">{skippedSummary(item)}</span>
                </div>
              )}
              <h1>
                <a href={`#job/${encodeURIComponent(item.slug)}`}>{item.title}</a>
              </h1>
              <div className="location">
                <MapPin size={14} />
                {item.location || "Location not specified"}
              </div>
            </div>
            <div className="review-nav">
              <IconButton label="Previous job (k)" disabled={pos === 0} onClick={() => go(pos - 1)}>
                <ArrowLeft size={16} />
              </IconButton>
              <IconButton
                label="Next job (j)"
                disabled={pos >= visible.length - 1}
                onClick={() => go(pos + 1)}
              >
                <ArrowRight size={16} />
              </IconButton>
            </div>
          </div>
          {isAnswers ? (
            <>
              <p className="tailor-oneline">
                <strong>Application answers</strong> · {state.answers?.source === "ashby" ? "Ashby" : "Greenhouse"} form
              </p>
              {state.answers?.status === "failed" ? (
                <p className="tailor-error">Couldn’t draft answers: {state.answers.error}</p>
              ) : (
                <>
                  {state.answers?.message && <p className="tailor-reason">{state.answers.message}</p>}
                  <AnswerList block={state.answers} e={answerEdits} disabled={busy} />
                </>
              )}
              <div className="review-actions">
                <button className="button" disabled={busy || state.answers?.status !== "ready"} onClick={() => answersDone()}>
                  {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}
                  Done
                  <kbd>Enter</kbd>
                </button>
                <button
                  className="button secondary"
                  disabled={busy || state.answers?.status !== "ready"}
                  onClick={() => answersDone(true)}
                >
                  Done & fill application <kbd>f</kbd>
                </button>
                {safeURL(item.apply_url || item.url) && (
                  <External href={item.apply_url || item.url} className="text-button">
                    Open application
                  </External>
                )}
              </div>
              <p className="keyboard-hint review-keys">
                <kbd>Enter</kbd> done (drafts you haven’t edited are approved) · <kbd>j</kbd>/<kbd>k</kbd> next/previous
              </p>
            </>
          ) : state.status === "failed" ? (
            <div className="tailor-error">
              <p>Couldn’t tailor this one: {state.error}</p>
              <button className="button secondary" disabled={busy} onClick={retry}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <BlockerBanner result={result} />
              <BlockedNotice turns={state.turns} />
              <p className="tailor-oneline">
                <strong>{BUCKETS[result.bucket] || result.bucket}</strong> resume ·{" "}
                {result.recommendation === "send as-is" ? "recommend sending as-is" : "recommend the tweaks"}
              </p>
              <p className="tailor-reason">{result.recommendation_reason}</p>
              <CommentReply turns={state.turns} message={result.message} />
              <Coverage coverage={state.coverage} />
              <div className="tailor-grid review-grid">
                <ResumePreview slug={item.slug} version={state.updated} small />
                <div className="tailor-side">
                  <Checks build={state.build} />
                  <h3>
                    {tweaks.length
                      ? `${tweaks.length} tweak${tweaks.length > 1 ? "s" : ""}`
                      : "No tweaks needed"}
                  </h3>
                  {tweaks.map((t) => (
                    <TweakCard
                      key={t.id}
                      t={t}
                      choice={choices[t.id]}
                      onChoose={choose}
                      feedback={feedback[t.id]}
                      onFeedback={setFeedbackFor}
                      disabled={busy}
                      coverage={state.coverage}
                    />
                  ))}
                </div>
              </div>
              {isAuto && state.apply?.status === "submitted" && (
                <p className="muted small">Already submitted: changes here won’t reach that application.</p>
              )}
              {jobWorking && (
                <div className="tailor-running" role="status">
                  <LoaderCircle className="spin" size={16} /> Working on your change. This job stays here and updates when
                  it’s done.
                </div>
              )}
              <div className="review-actions">
                {hasDecision(decisionBody(choices, feedback)) && (
                  <button className="button secondary" disabled={busy || jobWorking} onClick={applyChoices}>
                    Apply choices
                  </button>
                )}
                <button className="button" disabled={busy || jobWorking} onClick={done}>
                  {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}
                  {isAuto ? "Looks good" : "Done"}
                  <kbd>Enter</kbd>
                </button>
                {canFill && (
                  <button className="button secondary" disabled={busy} onClick={fillApp}>
                    <Sparkles size={15} />
                    {fillStatus ? "Looks good & fill again" : "Looks good & fill"} <kbd>f</kbd>
                  </button>
                )}
                {isAuto && ["queued", "running"].includes(fillStatus) && (
                  <span className="muted small">
                    <LoaderCircle className="spin" size={13} /> Filling in Chrome…
                  </span>
                )}
                {isAuto && ["ready_to_submit", "needs_you"].includes(fillStatus) && (
                  <a className="text-button" href={`#forms/${encodeURIComponent(item.slug)}`}>
                    {fillStatus === "ready_to_submit" ? "Filled: check & submit" : "The form needs you"}
                    <ArrowUpRight size={13} />
                  </a>
                )}
                {pending.length > 0 && (
                  <button className="button secondary" disabled={busy || jobWorking} onClick={useAll}>
                    Use all tweaks <kbd>y</kbd>
                  </button>
                )}
                {tweaks.some((t) => t.status === "applied") && !(isAuto && state.apply?.status === "submitted") && (
                  <button className="button secondary" disabled={busy || jobWorking} onClick={asIs}>
                    Send as-is <kbd>n</kbd>
                  </button>
                )}
                {safeURL(item.apply_url || item.url) && (
                  <External href={item.apply_url || item.url} className="text-button">
                    Open application
                  </External>
                )}
              </div>
              <p className="keyboard-hint review-keys">
                <kbd>Enter</kbd> {isAuto ? "looks good" : "done"} · {canFill && <><kbd>f</kbd> fill · </>}<kbd>y</kbd> use all · <kbd>n</kbd> as-is · <kbd>j</kbd>/<kbd>k</kbd> next/previous ·{" "}
                <kbd>o</kbd> PDF · <kbd>a</kbd> application
              </p>
              <ResumeComment
                resetKey={`${item.slug}|${state.updated}`}
                disabled={busy}
                onSend={(comment) =>
                  act({ ...decisionBody(choices, feedback), comment }, `${item.company}: comment sent`)
                }
              />
              <TailorDetails result={result} />
            </>
          )}
        </section>
      )}
    </>
  );
}
function JobPage({ slug, jobs, onStatus, onDelete, onJobsChanged }) {
  const [job, setJob] = useState(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setJob((j) => (j && j.slug === slug ? j : null));  // keep it on screen while it refreshes
    setError("");
    api(`/api/jobs/${encodeURIComponent(slug)}`)
      .then((j) => {
        if (active) setJob(j);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [slug, reload]);
  const current = job
    ? {
        ...job,
        status: jobs?.find((j) => j.slug === slug)?.status || job.status,
      }
    : null;
  return (
    <>
      <a className="back-link" href="#jobs">
        <ArrowLeft size={16} />
        My jobs
      </a>
      {error ? (
        <Empty title="Couldn’t open this job" text={error} />
      ) : !current ? (
        <Loading />
      ) : (
        <>
          <DetailContent record={current} files={<FileLinks job={current} />}>
            <StatusSelect job={current} onChange={onStatus} />
            <button
              className="button secondary"
              onClick={() =>
                document
                  .getElementById("tailor-panel")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <Sparkles size={16} />
              Tailored resume
            </button>
          </DetailContent>
          <TailorPanel
            slug={slug}
            onChanged={() => {
              setReload((n) => n + 1);
              onJobsChanged?.();  // the status shown above comes from the shared job list
            }}
          />
          <div className="detail-bottom">
            <span className="internal-id">{slug}</span>
            <button
              className="text-button danger-text"
              onClick={() => onDelete(current)}
            >
              <Trash2 size={14} />
              Remove job
            </button>
          </div>
        </>
      )}
    </>
  );
}
function InboxDetail({ item, loading, decide, busy }) {
  return (
    <>
      <a className="back-link" href="#inbox">
        <ArrowLeft size={16} />
        Back to inbox
      </a>
      {loading ? (
        <Loading />
      ) : !item ? (
        <Empty
          title="This job has left your inbox"
          text="You may have already kept or rejected it."
        />
      ) : (
        <>
          <DetailContent record={item.record} inSheet={item.in_sheet}>
            <div className="detail-decisions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => decide("reject", [item.job_id])}
              >
                <X size={16} />
                Reject
              </button>
              <button
                className="button"
                disabled={busy}
                onClick={() => decide("keep", [item.job_id])}
              >
                <Check size={16} />
                Keep
              </button>
            </div>
            {item.reason && (
              <div className="why">
                <Sparkles size={15} />
                <p>{item.reason}</p>
              </div>
            )}
          </DetailContent>
          <div className="internal-id">{item.job_id}</div>
        </>
      )}
    </>
  );
}

const FIELD_LABELS = {
  Company: "Company",
  Title: "Job title",
  Location: "Location",
  Category: "Category",
  Title_URL: "Posting link",
  Apply_URL: "Application link",
  Salary: "Salary",
  Posted_time: "Posted date",
  People_applied: "Applicants",
  Company_URL: "Company website",
  Company_size: "Company size",
  Company_follower: "Company followers",
  "Is this an internship": "Internship?",
  Company_Intro: "About the company",
  About_the_job: "Job description",
};
function AddPage({ onSaved }) {
  const [raw, setRaw] = useState(""),
    [fields, setFields] = useState(null),
    [headers, setHeaders] = useState(Object.keys(FIELD_LABELS)),
    [warnings, setWarnings] = useState([]),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [duplicate, setDuplicate] = useState(null);
  useEffect(() => {
    api("/api/quick-add/headers")
      .then((r) => setHeaders(r.headers))
      .catch((e) => setError(e.message));
  }, []);
  async function parse() {
    setBusy("parse");
    setError("");
    try {
      const data = await api("/api/quick-add/parse", { raw_text: raw });
      setFields(data.fields);
      setWarnings(data.warnings || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  async function save(force = false) {
    setBusy("save");
    setError("");
    try {
      if (!force) {
        const check = await api("/api/quick-add/check-duplicate", { fields });
        if (check.duplicate) {
          setDuplicate(check);
          return;
        }
      }
      const data = await api("/api/quick-add/save", { fields, force });
      setDuplicate(null);
      await onSaved(data.slug);
    } catch (e) {
      setError(e.message);
      setDuplicate(null);
    } finally {
      setBusy("");
    }
  }
  const basic = [
    "Company",
    "Title",
    "Location",
    "Title_URL",
    "Apply_URL",
    "Salary",
  ];
  function field(key) {
    return (
      <label
        key={key}
        className={
          ["About_the_job", "Company_Intro"].includes(key) ? "wide" : ""
        }
      >
        <span>
          {FIELD_LABELS[key] || key}
          {["Company", "Title"].includes(key) && <b className="required"> *</b>}
        </span>
        {["About_the_job", "Company_Intro"].includes(key) ? (
          <textarea
            rows={key === "About_the_job" ? 12 : 4}
            value={fields[key] || ""}
            onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
          />
        ) : key === "Is this an internship" ? (
          <select
            value={fields[key] || ""}
            onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
          >
            <option value="">Not specified</option>
            {["Yes", "No", "Maybe"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input
            type={key.endsWith("URL") ? "url" : "text"}
            required={["Company", "Title"].includes(key)}
            value={fields[key] || ""}
            onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
          />
        )}
      </label>
    );
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">FOUND SOMETHING GOOD?</div>
          <h1>Bring it into Loom.</h1>
          <p>Paste a job posting. We’ll take care of the busywork.</p>
        </div>
      </div>
      <div className="add-layout">
        <div>
          <div className="steps">
            <span className={!fields ? "current" : "complete"}>
              <i>{fields ? <Check size={13} /> : 1}</i>Paste a posting
            </span>
            <ChevronRight size={14} />
            <span className={fields ? "current" : ""}>
              <i>2</i>Review & save
            </span>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          <section className="surface paste-surface">
            <div className="section-title">
              <h2>
                {fields ? "Original posting" : "Start with the full picture"}
              </h2>
              <FileText size={20} />
            </div>
            <p className="muted">
              Copy the page text, including the role, company, description, and
              links.
            </p>
            <label>
              <span className="sr-only">Job posting text</span>
              <textarea
                className="paste-input"
                rows={fields ? 4 : 11}
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                placeholder={
                  "Paste a job posting here…\n\nLinkedIn, Handshake, a company careers page—anywhere you find your next opportunity."
                }
              />
            </label>
            <div className="paste-actions">
              <button
                className="text-button"
                disabled={!!busy}
                onClick={() => {
                  setRaw("");
                  setFields(null);
                  setWarnings([]);
                  setError("");
                }}
              >
                Clear
              </button>
              <button
                className="button"
                disabled={!!busy || !raw.trim()}
                onClick={parse}
              >
                {busy === "parse" ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <Sparkles size={17} />
                )}{" "}
                {busy === "parse"
                  ? "Reading the posting…"
                  : fields
                    ? "Fill form again"
                    : "Fill in form"}
              </button>
            </div>
            {busy === "parse" && (
              <div className="parse-progress" role="status">
                <div />
                <span>
                  Finding the details. This usually takes 10–30 seconds.
                </span>
              </div>
            )}
          </section>
          {fields && (
            <form
              className="surface review-form"
              onSubmit={(e) => {
                e.preventDefault();
                save();
              }}
            >
              <div className="section-title">
                <h2>Make it yours</h2>
                <span className="tag neutral">Review before saving</span>
              </div>
              {warnings.length > 0 && (
                <div className="warning-box" role="status">
                  {warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </div>
              )}
              <div className="form-fields">
                {basic.filter((k) => headers.includes(k)).map(field)}
                {field("About_the_job")}
              </div>
              <details className="more-fields">
                <summary>
                  More details
                  <ChevronDown size={16} />
                </summary>
                <div className="form-fields">
                  {headers
                    .filter((k) => !basic.includes(k) && k !== "About_the_job")
                    .map(field)}
                </div>
              </details>
              <div className="form-footer">
                <span>
                  Saved to My jobs as <strong>Not Applied</strong>
                </span>
                <button className="button" type="submit" disabled={!!busy}>
                  {busy === "save" ? (
                    <LoaderCircle size={17} className="spin" />
                  ) : (
                    <Check size={17} />
                  )}
                  Save job
                </button>
              </div>
            </form>
          )}
        </div>
        <aside className="add-note">
          <div className="note-icon">
            <Sparkles size={24} />
          </div>
          <h3>
            A good find deserves
            <br />a place to land.
          </h3>
          <p>
            Jobs you add go straight to your tracker, ready for your next step.
          </p>
          <div>
            <ShieldCheck size={17} />
            <span>You review every detail before it’s saved.</span>
          </div>
          <div>
            <LayoutGrid size={17} />
            <span>Already here? We’ll check for duplicates.</span>
          </div>
        </aside>
      </div>
      {duplicate && (
        <Modal
          title="This looks familiar"
          confirmLabel="Add anyway"
          confirm={() => save(true)}
          cancel={() => setDuplicate(null)}
          busy={!!busy}
        >
          <p>A matching job is already in your tracker.</p>
          <div className="duplicate-preview">
            <strong>{duplicate.existing.Company}</strong>
            <h3>{duplicate.existing.Title}</h3>
            <p>{duplicate.existing.Location}</p>
            <span className="tag neutral">
              {duplicate.existing.Status || "Not Applied"}
            </span>
          </div>
          <p className="muted small">
            {duplicate.match_reason}. Identical company, title, and location
            combinations cannot be added twice.
          </p>
        </Modal>
      )}
    </>
  );
}
function SystemPage({ system, error, retry }) {
  if (error)
    return (
      <Empty title="System status unavailable" text={error}>
        <button className="button" onClick={retry}>
          Try again
        </button>
      </Empty>
    );
  if (!system) return <Loading />;
  const run = system.last_run,
    sites = run?.stats?.sites || {},
    checked = system.checked.reduce((n, r) => n + r.count, 0);
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">BEHIND YOUR OPPORTUNITIES</div>
          <h1>A pulse on your search.</h1>
          <p>Your sources, recent checks, and available capacity.</p>
        </div>
        <span className="tag neutral">
          <ShieldCheck size={14} />
          View only
        </span>
      </div>
      {system.warnings.map((w) => (
        <div className="warning-box" key={w}>
          {w}
        </div>
      ))}
      <div className="system-stats">
        {[
          {
            label: "Waiting in inbox",
            n: system.inbox.pending,
            icon: InboxIcon,
          },
          { label: "Kept", n: system.inbox.kept, icon: Check },
          { label: "Rejected", n: system.inbox.rejected, icon: X },
          {
            label: "Live company boards",
            n: Object.values(system.boards).reduce((n, v) => n + v, 0),
            icon: LayoutGrid,
          },
        ].map(({ label, n, icon: Icon }) => (
          <div className="surface" key={label}>
            <Icon size={19} />
            <strong>{fmt(n)}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="system-grid">
        <section className="surface">
          <div className="section-title">
            <h2>Latest board check</h2>
            <Clock3 size={19} />
          </div>
          {run ? (
            <>
              <div className="run-summary">
                <strong>{dateLabel(run.finished || run.started, true)}</strong>
                <span className={`tag ${run.finished ? "success" : "neutral"}`}>
                  {run.finished ? "Completed" : "In progress"}
                </span>
              </div>
              <p className="muted small">
                {fmt(run.stats.written)} candidates written for description
                review
              </p>
              <div className="stat-table">
                <div className="stat-table-header">
                  <span>SOURCE</span>
                  <span>POSTINGS</span>
                  <span>CHANGED</span>
                </div>
                {Object.entries(sites).map(([site, data]) => (
                  <div key={site}>
                    <strong>{site}</strong>
                    <span>{fmt(data.postings)}</span>
                    <span>{fmt(data.changed)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="muted">No board check has run yet.</p>
          )}
        </section>
        <section className="surface">
          <div className="section-title">
            <h2>Description reviews</h2>
            <Sparkles size={19} />
          </div>
          <div className="large-stat">
            {fmt(checked)}
            <span>decisions recorded</span>
          </div>
          {system.checked.map((r) => (
            <div className="momentum-stat" key={`${r.stage}-${r.decision}`}>
              <span>
                {r.stage === "free" ? "Rule checks" : "Model checks"} ·{" "}
                {r.decision === "pass" ? "passed" : "dropped"}
              </span>
              <strong>{fmt(r.count)}</strong>
            </div>
          ))}
        </section>
        <section className="surface">
          <div className="section-title">
            <h2>Codex capacity</h2>
            <span className="tag neutral">Last recorded</span>
          </div>
          <p className="muted small">
            Usage from local session logs; readings may lag behind live usage.
          </p>
          {[
            { key: "five_hour", label: "5-hour window" },
            { key: "weekly", label: "Weekly window" },
          ].map(({ key, label }) => {
            const n = system.limits[`${key}_used`],
              reset = system.limits[`${key}_resets_at`];
            return (
              <div className="capacity" key={key}>
                <div>
                  <strong>{label}</strong>
                  <span>{n == null ? "Unavailable" : `${n}% used`}</span>
                </div>
                <progress
                  value={n == null ? 0 : Math.max(0, Math.min(100, n))}
                  max="100"
                  aria-label={`${label} used`}
                />
                <small>
                  {reset
                    ? `Resets ${dateLabel(reset, true)}`
                    : "No reset time available"}
                </small>
              </div>
            );
          })}
        </section>
        <section className="surface">
          <div className="section-title">
            <h2>Your sources</h2>
            <LayoutGrid size={19} />
          </div>
          {Object.entries(system.boards).map(([site, n], i) => (
            <div className="board-row" key={site}>
              <span>
                <i className={`source-dot dot-${i % 4}`} />
                {site}
              </span>
              <strong>
                {fmt(n)} <small>live boards</small>
              </strong>
            </div>
          ))}
        </section>
        <section className="surface phone-access">
          <div className="section-title">
            <h2>
              <Smartphone size={18} />
              Phone access
            </h2>
            <span className={`tag ${system.phone?.url ? "success" : "neutral"}`}>
              {system.phone?.url ? "On" : "Off"}
            </span>
          </div>
          {system.phone?.url ? (
            <p className="muted small">
              <a href={system.phone.url}>{system.phone.url}</a> · only your
              Tailscale devices, since {dateLabel(system.phone.since, true)}
            </p>
          ) : (
            <p className="muted small">
              Turn it on with <code>python scripts/phone.py on</code>. It needs
              Tailscale on this Mac and on your phone.
            </p>
          )}
        </section>
      </div>
      <section className="surface diagnostics">
        <details>
          <summary>
            <span>
              <Settings2 size={18} />
              Local diagnostics
            </span>
            <ChevronDown size={18} />
          </summary>
          <div className="diagnostics-grid">
            {Object.entries(system.diagnostics).map(([group, entries]) => (
              <div key={group}>
                <h3>{group}</h3>
                {Object.entries(entries).map(([name, value]) => (
                  <div className="diagnostic" key={name}>
                    <span>{name}</span>
                    <span className={value ? "available" : "unavailable"}>
                      {value ? "Available" : "Missing"}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </details>
      </section>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
