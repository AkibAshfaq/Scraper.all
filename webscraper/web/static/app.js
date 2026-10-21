// Webscraper UI. Scraped text comes from arbitrary websites, so it is only
// ever inserted with textContent / text nodes, never as HTML.
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  store: "staged",      // which sidebar tab is shown
  sessions: [],
  session: null,        // full session currently open
  rank: null,           // rank of the document open in the reader
  config: null,
};

// ---------- API ----------

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(errorText(data) || `Request failed (${resp.status})`);
  return data;
}

function errorText(data) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  return "";
}

// ---------- small DOM helpers ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function safeHref(url) {
  return /^https?:\/\//i.test(url) ? url : null;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Returns text split into text nodes and <mark> nodes for each term match.
function highlight(text, terms) {
  const words = terms.filter((t) => t.length > 1);
  if (!text || !words.length) return [text || ""];
  const re = new RegExp(`(${words.map(escapeRegExp).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? el("mark", {}, part) : part));
}

function terms() {
  const words = (state.session?.keyword || "").split(/\s+/);
  const filter = $("filter").value.trim();
  return filter ? [...words, filter] : words;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

let toastTimer;
function toast(message, isError = false) {
  const box = $("toast");
  box.textContent = message;
  box.className = isError ? "toast error" : "toast";
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), isError ? 6000 : 3500);
}

// ---------- sidebar ----------

async function loadSessions() {
  try {
    state.sessions = await api(`/api/sessions?store=${state.store}`);
  } catch (err) {
    state.sessions = [];
    toast(err.message, true);
  }
  renderSessions();
}

function renderSessions() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.store === state.store));
  });
  const ttl = state.config?.staging_ttl_hours ?? 24;
  $("store-hint").textContent =
    state.store === "staged"
      ? `Unsaved searches. Deleted automatically after ${ttl} h.`
      : "Searches stored in the permanent database.";

  const list = $("session-list");
  list.replaceChildren();
  if (!state.sessions.length) {
    list.append(el("li", { class: "none" }, state.store === "staged" ? "No temporary searches." : "Nothing saved yet."));
    return;
  }
  for (const s of state.sessions) {
    list.append(
      el("li", {},
        el("button", {
          type: "button",
          "aria-current": String(s.id === state.session?.id),
          onclick: () => go(s.id),
        },
          el("span", { class: "kw" }, s.keyword),
          el("span", { class: "sub" }, `${s.page_count} documents · ${fmtDate(s.created_at)}`),
        ),
      ),
    );
  }
}

// ---------- session view ----------

async function openSession(id, rank = null) {
  try {
    state.session = await api(`/api/sessions/${encodeURIComponent(id)}`);
  } catch (err) {
    toast(err.message, true);
    go(null);
    return;
  }
  if (state.session.store !== state.store) {
    state.store = state.session.store;
    await loadSessions();
  } else {
    renderSessions();
  }
  renderSession();
  openDoc(rank);
}

function renderSession() {
  const s = state.session;
  $("welcome").hidden = Boolean(s);
  $("session-view").hidden = !s;
  if (!s) return;

  $("session-title").replaceChildren(
    s.keyword,
    el("span", { class: `badge ${s.store}` }, s.store === "saved" ? "Saved" : "Temporary"),
  );
  $("session-meta").textContent =
    `${s.success_count} of ${s.pages.length} pages scraped · via ${s.provider} · ${fmtDate(s.created_at)}`;
  $("save-btn").hidden = s.store !== "staged";
  $("discard-btn").hidden = s.store !== "staged";
  $("dl-json").href = `/api/sessions/${s.id}/export?format=json`;
  $("dl-csv").href = `/api/sessions/${s.id}/export?format=csv`;
  renderDocs();
}

function renderDocs() {
  const s = state.session;
  const filter = $("filter").value.trim().toLowerCase();
  const hideFailed = $("hide-failed").checked;
  const words = terms();

  const visible = s.pages.filter((p) => {
    if (hideFailed && p.error) return false;
    if (!filter) return true;
    return [p.title, p.search_title, p.url, p.description, p.search_snippet, p.content]
      .some((field) => (field || "").toLowerCase().includes(filter));
  });

  const list = $("doc-list");
  list.replaceChildren(
    ...visible.map((p) =>
      el("li", {},
        el("button", {
          type: "button",
          class: p.error ? "doc failed" : "doc",
          "aria-current": String(p.rank === state.rank),
          onclick: () => go(s.id, p.rank),
        },
          el("span", { class: "rank" }, p.rank),
          el("span", { class: "title" }, highlight(p.title || p.search_title || p.url, words)),
          el("span", { class: "url" }, p.url),
          p.error
            ? el("span", { class: "err" }, `Not scraped: ${p.error}`)
            : el("span", { class: "snippet" }, highlight(p.description || p.search_snippet || p.content.slice(0, 240), words)),
        ),
      ),
    ),
  );
  $("doc-empty").hidden = visible.length > 0;
}

// ---------- reader ----------

function openDoc(rank) {
  const page = rank == null ? null : state.session?.pages.find((p) => p.rank === rank);
  state.rank = page ? page.rank : null;
  $("reader").hidden = !page;
  document.querySelectorAll(".doc").forEach((d) => {
    d.setAttribute("aria-current", String(d.querySelector(".rank").textContent === String(state.rank)));
  });
  if (!page) return;

  const words = terms();
  $("reader-rank").textContent = `#${page.rank}`;
  $("reader-rank").className = "rank";
  $("reader-title").replaceChildren(...highlight(page.title || page.search_title || page.url, words));

  const link = $("reader-url");
  link.textContent = page.url;
  const href = safeHref(page.url);
  if (href) link.href = href; else link.removeAttribute("href");

  $("reader-error").hidden = !page.error;
  $("reader-error").textContent = page.error ? `This page could not be scraped: ${page.error}` : "";
  $("reader-desc").replaceChildren(...highlight(page.description || page.search_snippet, words));

  const paragraphs = (page.content || "").split(/\n+/).filter(Boolean);
  $("reader-content").replaceChildren(
    ...(paragraphs.length
      ? paragraphs.map((p) => el("p", {}, highlight(p, words)))
      : [el("p", { class: "muted" }, "No text content was extracted.")]),
  );

  $("reader-headings-wrap").hidden = !page.headings.length;
  $("reader-headings-count").textContent = page.headings.length;
  $("reader-headings").replaceChildren(...page.headings.map((h) => el("li", {}, h)));

  $("reader-links-wrap").hidden = !page.links.length;
  $("reader-links-count").textContent = page.links.length;
  $("reader-links").replaceChildren(
    ...page.links.map((url) =>
      el("li", {}, el("a", { href: safeHref(url), target: "_blank", rel: "noopener noreferrer" }, url)),
    ),
  );
  $("reader").querySelector(".reader-body").scrollTop = 0;
}

// ---------- routing: #/s/<session id>[/<rank>] ----------

function go(id, rank = null) {
  const hash = id ? `#/s/${id}${rank != null ? `/${rank}` : ""}` : "#/";
  if (location.hash === hash) route();
  else location.hash = hash;
}

async function route() {
  const match = location.hash.match(/^#\/s\/([\w-]+)(?:\/(\d+))?$/);
  if (!match) {
    state.session = null;
    state.rank = null;
    $("reader").hidden = true;
    renderSession();
    renderSessions();
    return;
  }
  const [, id, rank] = match;
  const rankNum = rank ? Number(rank) : null;
  if (state.session?.id === id) openDoc(rankNum);
  else await openSession(id, rankNum);
}

// ---------- actions ----------

async function onSearch(event) {
  event.preventDefault();
  const keyword = $("keyword").value.trim();
  if (!keyword) return;
  const limit = Number($("limit").value);

  const button = $("search-btn");
  button.disabled = true;
  button.textContent = "Searching…";
  $("progress-text").textContent =
    `Searching for “${keyword}” and scraping up to ${limit} pages. This can take a minute.`;
  $("progress").hidden = false;
  try {
    const session = await api("/api/search", {
      method: "POST",
      body: JSON.stringify({ keyword, limit }),
    });
    $("filter").value = "";
    state.session = session;
    state.rank = null;
    state.store = "staged";
    renderSession();
    $("reader").hidden = true;
    await loadSessions();
    go(session.id);
    toast(`Scraped ${session.success_count} of ${session.pages.length} pages. Saved to file ${session.file.split(/[\\/]/).pop()}`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Search";
    $("progress").hidden = true;
  }
}

async function onSave() {
  const s = state.session;
  try {
    state.session = await api(`/api/sessions/${s.id}/save`, { method: "POST" });
    state.store = "saved";
    await loadSessions();
    renderSession();
    openDoc(state.rank);
    toast(`“${s.keyword}” saved to the database.`);
  } catch (err) {
    toast(err.message, true);
  }
}

async function onDiscard() {
  const s = state.session;
  if (!confirm(`Discard the temporary search “${s.keyword}”? Its data will be deleted.`)) return;
  try {
    await api(`/api/sessions/${s.id}`, { method: "DELETE" });
    state.session = null;
    await loadSessions();
    go(null);
    toast("Search discarded.");
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- startup ----------

async function init() {
  $("search-form").addEventListener("submit", onSearch);
  $("save-btn").addEventListener("click", onSave);
  $("discard-btn").addEventListener("click", onDiscard);
  $("reader-close").addEventListener("click", () => go(state.session.id));
  $("filter").addEventListener("input", () => { renderDocs(); openDoc(state.rank); });
  $("hide-failed").addEventListener("change", renderDocs);
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      state.store = tab.dataset.store;
      loadSessions();
    }),
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("reader").hidden) go(state.session.id);
  });
  window.addEventListener("hashchange", route);

  try {
    state.config = await api("/api/config");
    $("provider-line").textContent = `Search providers: ${state.config.provider.split(",").join(" → ")}`;
    $("version").textContent = `v${state.config.version}`;
  } catch {
    // UI still works without config; hints fall back to defaults.
  }
  await loadSessions();
  await route();
  $("keyword").focus();
}

init();
