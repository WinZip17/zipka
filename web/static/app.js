const log = document.getElementById("log");
const statusEl = document.getElementById("status");
const mindEl = document.getElementById("mind");
const pendingEl = document.getElementById("pending");

function addBubble(text, who) {
  const div = document.createElement("div");
  div.className = `bubble ${who}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
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

async function uploadBook(file, member) {
  if (!file) return;
  addBubble(`(книга) ${file.name}`, "user");
  addBubble("Читаю файл…", "bot");
  const fd = new FormData();
  fd.append("file", file);
  if (member) fd.append("member", member);
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

document.getElementById("book-file").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  await uploadBook(file);
});

document.getElementById("book-file-side").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  const member = document.getElementById("book-member").value.trim();
  e.target.value = "";
  await uploadBook(file, member || null);
});

document.getElementById("book-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const path = document.getElementById("book-path").value.trim();
  const member = document.getElementById("book-member").value.trim();
  if (!path) return;
  let message = `изучи ${path}`;
  if (member) message += ` внутри ${member}`;
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
chatPanel.addEventListener("drop", async (e) => {
  e.preventDefault();
  chatPanel.classList.remove("drop-active");
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  await uploadBook(file);
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
    addBubble(data.description || data.message || JSON.stringify(data), "bot");
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
