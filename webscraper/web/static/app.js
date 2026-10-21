// Webscraper UI. Scraped text comes from arbitrary websites, so it is only
// ever inserted with textContent / text nodes, never as HTML.
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  store: "staged",      // which sidebar tab is shown
  sessions: [],
  session: null,        // full session currently open
  rank: null,           // rank of the document open in the reader
  view: "docs",         // "docs" | "chat"
  chats: new Map(),     // session id -> [{role, content, pending?, error?}]
  chatAbort: null,      // AbortController of the reply being streamed
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
          el("span", { class: "sub" }, `${s.page_count} document${s.page_count === 1 ? "" : "s"} · ${fmtDate(s.created_at)}`),
        ),
      ),
    );
  }
}

// ---------- session view ----------

async function openSession(id, rank = null) {
  if (state.session?.id !== id) stopChat();
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
  const n = s.pages.length;
  $("session-meta").textContent =
    `${n} document${n === 1 ? "" : "s"} · via ${s.provider} · ${fmtDate(s.created_at)}`;
  $("docs-count").textContent = n;
  $("save-btn").hidden = s.store !== "staged";
  $("discard-btn").hidden = s.store !== "staged";
  $("summary-btn").hidden = !state.config?.chat_enabled;
  $("tab-chat").hidden = !state.config?.chat_enabled;
  $("dl-json").href = `/api/sessions/${s.id}/export?format=json`;
  $("dl-csv").href = `/api/sessions/${s.id}/export?format=csv`;
  renderDocs();
  setView(state.view);
}

function setView(view, focus = false) {
  if (!state.config?.chat_enabled) view = "docs";
  state.view = view;
  for (const tab of document.querySelectorAll(".vtab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === view));
  }
  $("docs-pane").hidden = view !== "docs";
  $("chat-pane").hidden = view !== "chat";
  if (view === "chat") {
    renderChat();
    if (focus) $("chat-input").focus();
  }
}

function renderDocs() {
  const s = state.session;
  const filter = $("filter").value.trim().toLowerCase();
  const words = terms();

  // The API only returns successfully scraped pages; failed fetches aren't shown.
  const visible = s.pages.filter((p) => {
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
          class: "doc",
          "aria-current": String(p.rank === state.rank),
          onclick: () => go(s.id, p.rank),
        },
          el("span", { class: "rank" }, p.rank),
          el("span", { class: "title" }, highlight(p.title || p.search_title || p.url, words)),
          el("span", { class: "url" }, p.url),
          el("span", { class: "snippet" }, highlight(p.description || p.search_snippet || p.content.slice(0, 240), words)),
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

// ---------- AI chat ----------

const SUGGESTIONS = [
  "What are the key facts and figures?",
  "Where do the sources disagree?",
  "Explain this topic to a beginner.",
];

function chatFor(id) {
  if (!state.chats.has(id)) state.chats.set(id, []);
  return state.chats.get(id);
}

function renderChat() {
  const s = state.session;
  if (!s) return;
  const messages = chatFor(s.id);
  const busy = Boolean(state.chatAbort);

  $("chat-empty").hidden = messages.length > 0;
  $("chat-clear").hidden = messages.length === 0 || busy;
  $("chat-send").textContent = busy ? "Stop" : "Send";
  $("chat-send").classList.toggle("danger-quiet", busy);
  $("chat-send").classList.toggle("primary", !busy);
  $("summarize-btn").disabled = busy;

  const log = $("chat-log");
  const stickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.replaceChildren(...messages.map(renderMessage));
  if (stickToBottom || busy) log.scrollTop = log.scrollHeight;
}

function renderMessage(m) {
  if (m.role === "user") {
    return el("div", { class: `msg user${m.error ? " failed" : ""}` }, el("div", { class: "bubble" }, m.content));
  }
  const body = el("div", { class: "bubble md" });
  if (m.content) body.append(renderMarkdown(m.content));
  if (m.pending && !m.content) body.append(el("span", { class: "typing" }, "Reading the documents", el("i"), el("i"), el("i")));
  if (m.stopped) body.append(el("p", { class: "muted small" }, "Stopped."));
  if (m.error) body.append(el("p", { class: "error-box" }, m.error));
  return el("div", { class: "msg assistant" }, el("span", { class: "avatar", "aria-hidden": "true" }, "✦"), body);
}

let renderQueued = false;
function scheduleChatRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderChat();
  });
}

async function sendChat(text) {
  const s = state.session;
  text = text.trim();
  if (!s || !text || state.chatAbort) return;
  setView("chat");

  const messages = chatFor(s.id);
  const question = { role: "user", content: text };
  const reply = { role: "assistant", content: "", pending: true };
  messages.push(question, reply);
  $("chat-input").value = "";
  autoGrow();

  const controller = new AbortController();
  state.chatAbort = controller;
  renderChat();

  // History sent to the server: completed turns only (failed ones are dropped).
  const history = messages
    .filter((m) => m !== reply && !m.error && m.content)
    .map(({ role, content }) => ({ role, content }));

  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(s.id)}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(errorText(data) || `Chat failed (${resp.status})`);
    }
    await readEvents(resp, (event) => {
      if (event.type === "text") {
        reply.content += event.text;
        scheduleChatRender();
      } else if (event.type === "error") {
        throw new Error(event.message);
      }
    });
  } catch (err) {
    if (controller.signal.aborted) {
      reply.stopped = true;
      if (!reply.content) question.error = true;
    } else {
      reply.error = err.message;
      question.error = true;
    }
  } finally {
    reply.pending = false;
    if (state.chatAbort === controller) state.chatAbort = null;
    if (state.session?.id === s.id) renderChat();
  }
}

// Reads a newline-delimited JSON stream, calling onEvent for each line.
async function readEvents(resp, onEvent) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function stopChat() {
  state.chatAbort?.abort();
}

function autoGrow() {
  const box = $("chat-input");
  box.style.height = "auto";
  box.style.height = `${Math.min(box.scrollHeight, 180)}px`;
  box.style.overflowY = box.scrollHeight > 180 ? "auto" : "hidden";
}

// Minimal Markdown -> DOM (headings, lists, paragraphs, bold/italic/code,
// [#N] citations). Builds nodes directly so nothing is parsed as HTML.
function renderMarkdown(src) {
  const frag = document.createDocumentFragment();
  let para = [];
  let list = null;
  const flush = () => {
    if (para.length) frag.append(el("p", {}, inline(para.join(" "))));
    para = [];
  };
  for (const raw of src.replace(/\r/g, "").split("\n")) {
    const line = raw.trim();
    let m;
    if (!line) { flush(); list = null; continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flush(); list = null;
      frag.append(el(`h${Math.min(m[1].length + 2, 6)}`, {}, inline(m[2])));
    } else if ((m = line.match(/^([-*•]|\d+[.)])\s+(.*)$/))) {
      flush();
      const ordered = /\d/.test(m[1]);
      if (!list || list.ordered !== ordered) {
        list = { ordered, node: el(ordered ? "ol" : "ul") };
        frag.append(list.node);
      }
      list.node.append(el("li", {}, inline(m[2])));
    } else if (/^([-*_])\1{2,}$/.test(line)) {
      flush(); list = null;
      frag.append(el("hr"));
    } else if (line.startsWith(">")) {
      flush(); list = null;
      frag.append(el("blockquote", {}, inline(line.replace(/^>\s?/, ""))));
    } else {
      list = null;
      para.push(line);
    }
  }
  flush();
  return frag;
}

function inline(text) {
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[#\d+(?:\s*,\s*#?\d+)*\]|\*[^*\s][^*]*\*)/g;
  return text.split(re).map((part, i) => {
    if (i % 2 === 0) return part;
    if (part.startsWith("**")) return el("strong", {}, part.slice(2, -2));
    if (part.startsWith("`")) return el("code", {}, part.slice(1, -1));
    if (part.startsWith("[#")) return el("span", { class: "cites" }, part.match(/\d+/g).map((n) => cite(Number(n))));
    return el("em", {}, part.slice(1, -1));
  });
}

function cite(rank) {
  const s = state.session;
  const page = s?.pages.find((p) => p.rank === rank);
  if (!page) return el("span", { class: "cite static" }, rank);
  return el("button", {
    type: "button",
    class: "cite",
    title: page.title || page.url,
    onclick: () => go(s.id, rank),
  }, rank);
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
    stopChat();
    state.chats.delete(s.id);
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
  document.querySelectorAll(".vtab").forEach((tab) =>
    tab.addEventListener("click", () => setView(tab.dataset.view, true)),
  );
  $("summary-btn").addEventListener("click", () => {
    setView("chat", true);
    if (!chatFor(state.session.id).length) sendChat(state.config.summary_prompt);
  });
  $("summarize-btn").addEventListener("click", () => sendChat(state.config.summary_prompt));
  $("chat-suggestions").replaceChildren(
    ...SUGGESTIONS.map((q) => el("button", { type: "button", class: "chip", onclick: () => sendChat(q) }, q)),
  );
  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (state.chatAbort) stopChat();
    else sendChat($("chat-input").value);
  });
  $("chat-input").addEventListener("input", autoGrow);
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("chat-form").requestSubmit();
    }
  });
  $("chat-clear").addEventListener("click", () => {
    state.chats.delete(state.session.id);
    renderChat();
    $("chat-input").focus();
  });
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
    $("chat-model").textContent = state.config.chat_model;
  } catch {
    // UI still works without config; hints fall back to defaults.
  }
  await loadSessions();
  await route();
  $("keyword").focus();
}

init();
