const log = document.getElementById("log");
const statusEl = document.getElementById("status");
const mindEl = document.getElementById("mind");
const pendingEl = document.getElementById("pending");
const pendingBox = document.getElementById("pending-file");
const pendingName = document.getElementById("pending-name");
const pendingComment = document.getElementById("pending-comment");
const historySentinel = document.getElementById("history-sentinel");

const PAGE_SIZE = 30;
let stagedFile = null;
let oldestIndex = null;
let hasMoreHistory = false;
let loadingHistory = false;
let bootDone = false;

function roleToWho(role) {
  return role === "user" ? "user" : "bot";
}

function makeBubble(text, who) {
  const div = document.createElement("div");
  div.className = `bubble ${who}`;
  div.textContent = text;
  return div;
}

function addBubble(text, who, { prepend = false, scroll = true } = {}) {
  const div = makeBubble(text, who);
  if (prepend) {
    const anchor = historySentinel.nextSibling;
    log.insertBefore(div, anchor);
  } else {
    log.appendChild(div);
    if (scroll) log.scrollTop = log.scrollHeight;
  }
  return div;
}

function updateSentinel() {
  if (hasMoreHistory) {
    historySentinel.classList.remove("hidden");
    historySentinel.textContent = loadingHistory ? "загрузка…" : "↑ прокрути выше за старыми";
    historySentinel.classList.toggle("loading", loadingHistory);
  } else {
    historySentinel.classList.add("hidden");
  }
}

async function fetchHistory({ before = null, limit = PAGE_SIZE } = {}) {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (before !== null && before !== undefined) qs.set("before", String(before));
  const res = await fetch(`/api/chat/history?${qs}`);
  if (!res.ok) throw new Error("history failed");
  return res.json();
}

async function loadInitialHistory() {
  loadingHistory = true;
  updateSentinel();
  try {
    const data = await fetchHistory({ limit: PAGE_SIZE });
    hasMoreHistory = !!data.has_more;
    oldestIndex = data.oldest_index;
    for (const msg of data.messages || []) {
      addBubble(msg.content, roleToWho(msg.role), { scroll: false });
    }
    log.scrollTop = log.scrollHeight;
  } catch (_) {
    hasMoreHistory = false;
  } finally {
    loadingHistory = false;
    updateSentinel();
  }
}

async function loadOlderHistory() {
  if (!hasMoreHistory || loadingHistory || oldestIndex === null || oldestIndex <= 0) return;
  loadingHistory = true;
  updateSentinel();
  const prevHeight = log.scrollHeight;
  const prevTop = log.scrollTop;
  try {
    const data = await fetchHistory({ before: oldestIndex, limit: PAGE_SIZE });
    hasMoreHistory = !!data.has_more;
    oldestIndex = data.oldest_index;
    const msgs = data.messages || [];
    // prepend in chronological order
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      addBubble(msgs[i].content, roleToWho(msgs[i].role), { prepend: true, scroll: false });
    }
    log.scrollTop = log.scrollHeight - prevHeight + prevTop;
  } catch (_) {
    /* keep flags */
  } finally {
    loadingHistory = false;
    updateSentinel();
  }
}

log.addEventListener("scroll", () => {
  if (!bootDone) return;
  if (log.scrollTop <= 48) loadOlderHistory();
});

function stageFile(file) {
  if (!file) return;
  stagedFile = file;
  pendingName.textContent = file.name;
  const sideComment = document.getElementById("book-comment");
  pendingComment.value =
    document.getElementById("msg").value.trim() ||
    (sideComment && sideComment.value.trim()) ||
    "";
  pendingBox.classList.remove("hidden");
  addBubble(
    `Файл прикреплён: ${file.name}. Добавь комментарий и нажми «Изучить».`,
    "bot"
  );
}

function clearStaged() {
  stagedFile = null;
  pendingBox.classList.add("hidden");
  pendingComment.value = "";
  pendingName.textContent = "файл";
}

async function refreshStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  statusEl.textContent =
    `Ollama: ${data.ollama ? "OK" : "offline"} · ${data.model} · ` +
    `eyes ${data.eyes ? "on" : "off"} · ears ${data.ears ? "on" : "off"}`;
  mindEl.textContent = JSON.stringify(data.mind, null, 2);
  const pendingRes = await fetch("/api/pending");
  const pending = await pendingRes.json();
  pendingEl.textContent = pending.pending
    ? JSON.stringify(pending.pending, null, 2)
    : "нет ожидающего патча";
}

async function uploadBook(file, member, comment) {
  if (!file) return;
  const note = comment ? ` — ${comment}` : "";
  addBubble(`(книга) ${file.name}${note}`, "user");
  addBubble("Читаю файл…", "bot");
  const fd = new FormData();
  fd.append("file", file);
  if (member) fd.append("member", member);
  if (comment) fd.append("comment", comment);
  const res = await fetch("/api/upload-book", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    addBubble(data.detail || "Ошибка загрузки", "bot");
    return;
  }
  addBubble(data.reply || data.digest || "Готово", "bot");
  refreshStatus();
}

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("msg");
  const message = input.value.trim();
  if (stagedFile) {
    const comment = pendingComment.value.trim() || message;
    input.value = "";
    const file = stagedFile;
    const member = document.getElementById("book-member").value.trim();
    clearStaged();
    await uploadBook(file, member || null, comment || null);
    return;
  }
  if (!message) return;
  addBubble(message, "user");
  input.value = "";
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();
  addBubble(data.reply, "bot");
  refreshStatus();
});

document.getElementById("book-file").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  stageFile(file);
});

document.getElementById("book-file-side").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  stageFile(file);
});

document.getElementById("pending-cancel").addEventListener("click", () => {
  clearStaged();
  addBubble("Прикрепление отменено.", "bot");
});

document.getElementById("pending-read").addEventListener("click", async () => {
  if (!stagedFile) return;
  const comment = pendingComment.value.trim();
  const member = document.getElementById("book-member").value.trim();
  const file = stagedFile;
  clearStaged();
  await uploadBook(file, member || null, comment || null);
});

document.getElementById("book-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const path = document.getElementById("book-path").value.trim();
  const member = document.getElementById("book-member").value.trim();
  const comment = document.getElementById("book-comment").value.trim();
  if (!path) return;
  let message = `изучи ${path}`;
  if (member) message += ` внутри ${member}`;
  if (comment) message += ` комментарий: ${comment}`;
  addBubble(message, "user");
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();
  addBubble(data.reply, "bot");
  refreshStatus();
});

const chatPanel = document.querySelector(".chat-panel");
chatPanel.addEventListener("dragover", (e) => {
  e.preventDefault();
  chatPanel.classList.add("drop-active");
});
chatPanel.addEventListener("dragleave", () => {
  chatPanel.classList.remove("drop-active");
});
chatPanel.addEventListener("drop", (e) => {
  e.preventDefault();
  chatPanel.classList.remove("drop-active");
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  stageFile(file);
});

document.querySelectorAll("[data-eyes]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const action = btn.getAttribute("data-eyes");
    const res = await fetch("/api/eyes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (data.description) addBubble(data.description, "bot");
    else addBubble(data.message || JSON.stringify(data), "bot");
    if (data.comment) addBubble(data.comment, "bot");
    refreshStatus();
  });
});

document.querySelectorAll("[data-ears]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const action = btn.getAttribute("data-ears");
    const res = await fetch("/api/ears", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, seconds: 5 }),
    });
    const data = await res.json();
    if (data.heard) addBubble(`(уши) ${data.heard}`, "user");
    if (data.comment) addBubble(data.comment, "bot");
    addBubble(data.reply || data.message || JSON.stringify(data), "bot");
    refreshStatus();
  });
});

document.getElementById("reflect").addEventListener("click", async () => {
  const res = await fetch("/api/reflect", { method: "POST" });
  const data = await res.json();
  mindEl.textContent = JSON.stringify(data, null, 2);
  addBubble("Рефлексия выполнена.", "bot");
});

document.getElementById("approve").addEventListener("click", async () => {
  const res = await fetch("/api/approve", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    addBubble(data.detail || "Нет патча", "bot");
  } else {
    addBubble(`Патч применён: ${data.id}`, "bot");
  }
  refreshStatus();
});

document.getElementById("learn-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = document.getElementById("learn-q").value.trim();
  if (!q) return;
  const res = await fetch("/api/learn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: q }),
  });
  const data = await res.json();
  addBubble(data.summary || JSON.stringify(data), "bot");
  refreshStatus();
});

refreshStatus();
setInterval(refreshStatus, 15000);

(async function boot() {
  await loadInitialHistory();
  bootDone = true;
  try {
    const res = await fetch("/api/proactive/hello");
    const data = await res.json();
    if (data.message) addBubble(data.message, "bot");
  } catch (_) {
    /* ignore */
  }
})();

setInterval(async () => {
  try {
    const res = await fetch("/api/proactive/ping");
    const data = await res.json();
    if (data.message) addBubble(data.message, "bot");
    refreshStatus();
  } catch (_) {
    /* ignore */
  }
}, 12 * 60 * 1000);
