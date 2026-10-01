import type {
  ChatModelsStatus,
  ComputeSettings,
  FinetuneStatusResponse,
  HistoryResponse,
  LlmBackendInfo,
  NewsAutoStatus,
  NewsRssSource,
  NewsSourcesResponse,
  NewsTelegramSource,
  PendingResponse,
  ReplyContextItem,
  StatusResponse,
} from "./types";

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

export async function sendChat(
  message: string,
  opts?: {
    reply_to?: ReplyContextItem | null;
    reply_chain?: ReplyContextItem[] | null;
  },
): Promise<{ reply?: string; detail?: string }> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      reply_to: opts?.reply_to || undefined,
      reply_chain: opts?.reply_chain?.length ? opts.reply_chain : undefined,
    }),
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
  const data = await parseJson<{
    heard?: string;
    comment?: string;
    reply?: string;
    message?: string;
    detail?: string;
    recording?: boolean;
    skipped_chat?: boolean;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : data.message || "ears failed",
    );
  }
  return data;
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

export async function setCompute(mode: string, gpu_layers?: number | null) {
  const res = await fetch("/api/settings/compute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode,
      gpu_layers: gpu_layers ?? undefined,
    }),
  });
  const data = await parseJson<{
    ok?: boolean;
    compute?: ComputeSettings;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Не удалось сменить compute");
  }
  return data;
}

export async function setChatModel(model_id: string) {
  const res = await fetch("/api/settings/chat-model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id }),
  });
  const data = await parseJson<{
    ok?: boolean;
    chat_models?: ChatModelsStatus;
    models?: ChatModelsStatus;
    llm?: LlmBackendInfo;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Не удалось сменить модель чата",
    );
  }
  return data;
}

export async function setModels(opts: {
  chat_gguf?: string | null;
  code_gguf?: string | null;
}) {
  const res = await fetch("/api/settings/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_gguf: opts.chat_gguf || undefined,
      code_gguf: opts.code_gguf || undefined,
    }),
  });
  const data = await parseJson<{
    ok?: boolean;
    chat_models?: ChatModelsStatus;
    models?: ChatModelsStatus;
    llm?: LlmBackendInfo;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Не удалось сменить модели",
    );
  }
  return data;
}

export async function setSoftEvolveDialogue(enabled: boolean) {
  const res = await fetch("/api/settings/soft-evolve-dialogue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  const data = await parseJson<{
    ok?: boolean;
    soft_evolve_from_dialogue?: boolean;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : "Не удалось сохранить soft-evolve",
    );
  }
  return data;
}

export async function setSensorsEnabled(enabled: boolean) {
  const res = await fetch("/api/settings/sensors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  const data = await parseJson<{
    ok?: boolean;
    sensors_enabled?: boolean;
    eyes?: boolean;
    ears?: boolean;
    detail?: string;
  }>(res);
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Не удалось сохранить сенсоры",
    );
  }
  return data;
}

export async function fetchFinetuneStatus(): Promise<FinetuneStatusResponse> {
  const res = await fetch("/api/finetune/status");
  return parseJson(res);
}

export async function proposeFinetune() {
  const res = await fetch("/api/finetune/propose", { method: "POST" });
  const data = await parseJson<{
    pending?: FinetuneStatusResponse["pending"];
    message?: string;
    approve_phrase?: string;
    detail?: string;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось подготовить дообучение",
    );
  }
  return data;
}

export async function startFinetune() {
  const res = await fetch("/api/finetune/start", { method: "POST" });
  const data = await parseJson<{
    ok?: boolean;
    job_id?: string;
    pid?: number;
    log?: string;
    message?: string;
    detail?: string;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось запустить дообучение",
    );
  }
  return data;
}

export async function abortFinetune() {
  const res = await fetch("/api/finetune/abort", { method: "POST" });
  const data = await parseJson<{
    ok?: boolean;
    killed?: boolean;
    status?: FinetuneStatusResponse["status"];
    message?: string;
    detail?: string;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось сбросить дообучение",
    );
  }
  return data;
}

export async function finetuneResetInfo() {
  const res = await fetch("/api/finetune/reset-info");
  return parseJson<{ confirm_phrase?: string; base_gguf?: string }>(res);
}

export async function resetFinetune(confirm_phrase: string) {
  const res = await fetch("/api/finetune/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_phrase }),
  });
  const data = await parseJson<{
    ok?: boolean;
    message?: string;
    base_gguf?: string;
    detail?: string;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Не удалось сбросить дообучение",
    );
  }
  return data;
}

export async function fetchNewsSources(): Promise<NewsSourcesResponse> {
  const res = await fetch("/api/news/sources");
  return parseJson(res);
}

export async function fetchNewsAuto(): Promise<NewsAutoStatus> {
  const res = await fetch("/api/news/auto");
  return parseJson(res);
}

export async function saveNewsSources(body: {
  global_interval_min?: number | string | null;
  rss?: Array<string | NewsRssSource>;
  telegram?: Array<string | NewsTelegramSource>;
}): Promise<NewsSourcesResponse> {
  const res = await fetch("/api/news/sources", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await parseJson<NewsSourcesResponse & { detail?: string }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось сохранить источники",
    );
  }
  return data;
}

export async function setNewsSchedule(body: {
  global_interval_min?: number | string | null;
  rss?: string;
  telegram?: string;
  interval?: string | number;
}): Promise<NewsSourcesResponse> {
  const res = await fetch("/api/news/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await parseJson<NewsSourcesResponse & { detail?: string }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось сохранить расписание",
    );
  }
  return data;
}

export async function addNewsSource(body: {
  rss?: string;
  telegram?: string;
  interval?: string | number;
}): Promise<NewsSourcesResponse> {
  const res = await fetch("/api/news/sources/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await parseJson<NewsSourcesResponse & { detail?: string }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось добавить источник",
    );
  }
  return data;
}

export async function ingestNews() {
  const res = await fetch("/api/news/ingest", { method: "POST" });
  const data = await parseJson<{
    ok?: boolean;
    added?: number;
    sources?: { rss?: number; telegram?: number };
    errors?: string[];
    items?: { title?: string; source?: string; summary?: string }[];
    detail?: string;
  }>(res);
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Не удалось обновить новости",
    );
  }
  return data;
}

export async function proactiveHello() {
  const res = await fetch("/api/proactive/hello");
  return parseJson<{ message?: string }>(res);
}

export async function proactivePing(force = false) {
  const qs = force ? "?force=true" : "";
  const res = await fetch(`/api/proactive/ping${qs}`, {
    // restudy URL/файла + LLM может занять минуты
    signal: AbortSignal.timeout(5 * 60 * 1000),
  });
  return parseJson<{
    message?: string | null;
    skipped?: string | null;
    pings?: unknown;
    detail?: string;
  }>(res);
}

export const FILE_ACCEPT =
  ".txt,.md,.markdown,.fb2,.xml,.djvu,.djv,.zip,.rar,.py,.js,.mjs,.cjs,.ts,.tsx,.jsx,.java,.go,.rs,.c,.cpp,.h,.hpp,.cs,.rb,.php,.swift,.kt,.sql,.sh,.ps1,.json,.yaml,.yml,.toml,.html,.css,.scss,.vue,.svelte,.lua,.dart";
