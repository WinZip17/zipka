export type ChatMessage = {
  role: string;
  content: string;
  ts?: string | null;
};

export type HistoryResponse = {
  messages: ChatMessage[];
  has_more: boolean;
  oldest_index: number | null;
};

export type StatusLimits = {
  max_book_bytes?: number;
  max_book_human?: string;
  ram_available_bytes?: number | null;
  ram_available_human?: string | null;
};

export type LlmBackendInfo = {
  backend?: "gguf" | "ollama" | string;
  model?: string;
  model_path?: string;
  host?: string;
  available?: boolean;
};

export type SpeakerGuardSummary = {
  same_person?: boolean | null;
  confidence?: number | null;
  alert?: boolean;
  signals?: string[];
  reason?: string;
  alerts_count?: number;
};

export type UserProfileSummary = {
  name?: string;
  how_to_address?: string;
  personality_type?: string;
  character?: string[];
  peculiarities?: string[];
  mood?: string;
  mood_previous?: string;
  likes?: string[];
  dislikes?: string[];
  time_habits?: string[];
  current_state?: string;
  energy?: string;
  facts_count?: number;
  evidence_count?: number;
  updated_at?: string;
  style_ready?: boolean;
  style_samples?: number;
  speaker?: SpeakerGuardSummary;
};

export type StatusResponse = {
  ollama: boolean;
  llm?: LlmBackendInfo;
  model: string;
  vision_model?: string;
  eyes: boolean;
  ears: boolean;
  pending_patch?: boolean;
  models?: string[];
  limits?: StatusLimits;
  approve_phrase?: string;
  user?: UserProfileSummary;
  proactive?: {
    today?: string;
    used?: number;
    max?: number;
    remaining?: number;
    last_rare_ping_at?: string | null;
  };
};

export type PendingResponse = {
  pending: unknown;
  approve_phrase?: string;
};

async function parseJson<T>(res: Response): Promise<T> {
  return (await res.json().catch(() => ({}))) as T;
}

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch("/api/status");
  return parseJson(res);
}

export async function fetchPending(): Promise<PendingResponse> {
  const res = await fetch("/api/pending");
  return parseJson(res);
}

export async function fetchHistory(opts: {
  limit?: number;
  before?: number | null;
}): Promise<HistoryResponse> {
  const qs = new URLSearchParams({ limit: String(opts.limit ?? 30) });
  if (opts.before !== null && opts.before !== undefined) {
    qs.set("before", String(opts.before));
  }
  const res = await fetch(`/api/chat/history?${qs}`);
  if (!res.ok) throw new Error("history failed");
  return parseJson(res);
}

export async function sendChat(message: string): Promise<{ reply?: string; detail?: string }> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await parseJson<{ reply?: string; detail?: string }>(res);
  if (!res.ok) throw new Error(data.detail || `Ошибка чата (${res.status})`);
  return data;
}

export async function uploadBook(
  file: File,
  member?: string | null,
  comment?: string | null,
): Promise<{ reply?: string; digest?: string; detail?: string }> {
  const fd = new FormData();
  fd.append("file", file);
  if (member) fd.append("member", member);
  if (comment) fd.append("comment", comment);
  const res = await fetch("/api/upload-book", { method: "POST", body: fd });
  const data = await parseJson<{ reply?: string; digest?: string; detail?: string }>(res);
  if (!res.ok) throw new Error(data.detail || "Ошибка загрузки");
  return data;
}

export async function eyesAction(action: string, monitor = 1) {
  const res = await fetch("/api/eyes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, monitor }),
  });
  const data = await parseJson<{
    description?: string;
    message?: string;
    comment?: string;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d))).join("; ")
      : typeof detail === "string"
        ? detail
        : "Ошибка глаз";
    throw new Error(msg);
  }
  return data;
}

export async function earsAction(action: string, seconds = 5) {
  const res = await fetch("/api/ears", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, seconds }),
  });
  return parseJson<{
    heard?: string;
    comment?: string;
    reply?: string;
    message?: string;
    detail?: string;
  }>(res);
}

export async function approvePatch() {
  const res = await fetch("/api/approve", { method: "POST" });
  const data = await parseJson<{
    id?: string;
    detail?: string;
    frontend_rebuild?: string | null;
    files?: string[];
  }>(res);
  if (!res.ok) throw new Error(data.detail || "Нет патча");
  return data;
}

export async function learn(query: string) {
  const res = await fetch("/api/learn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  return parseJson<{ summary?: string }>(res);
}

export async function resetInfo() {
  const res = await fetch("/api/reset-learning/info");
  return parseJson<{ confirm_phrase?: string }>(res);
}

export async function resetLearning(confirm_phrase: string) {
  const res = await fetch("/api/reset-learning", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_phrase }),
  });
  const data = await parseJson<{ message?: string; detail?: string }>(res);
  if (!res.ok) throw new Error(data.detail || "Сброс не выполнен");
  return data;
}

export async function proactiveHello() {
  const res = await fetch("/api/proactive/hello");
  return parseJson<{ message?: string }>(res);
}

export async function proactivePing() {
  const res = await fetch("/api/proactive/ping");
  return parseJson<{ message?: string }>(res);
}

export const FILE_ACCEPT =
  ".txt,.md,.markdown,.fb2,.xml,.djvu,.djv,.zip,.rar,.py,.js,.mjs,.cjs,.ts,.tsx,.jsx,.java,.go,.rs,.c,.cpp,.h,.hpp,.cs,.rb,.php,.swift,.kt,.sql,.sh,.ps1,.json,.yaml,.yml,.toml,.html,.css,.scss,.vue,.svelte,.lua,.dart";
