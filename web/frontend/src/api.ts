export type ChatMessage = {
  role: string;
  content: string;
  ts?: string | null;
  reply_to?: {
    role?: string;
    content?: string;
    ts?: string | null;
  } | null;
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
  chat_model_id?: string;
  chat_model_label?: string;
};

export type ChatModelProfile = {
  id: string;
  label: string;
  blurb?: string;
  filename?: string;
  present?: boolean;
  path?: string | null;
  size_hint_gb?: number;
  active?: boolean;
};

export type ModelRoleBlock = {
  filename?: string;
  label?: string;
  present?: boolean;
  path?: string | null;
};

export type GgufFileInfo = {
  filename: string;
  path?: string;
  size_bytes?: number;
  size_gb?: number | null;
  label?: string;
  blurb?: string;
};

export type ChatModelsStatus = {
  active_id?: string;
  active_label?: string;
  active_path?: string | null;
  active_present?: boolean;
  models_dir?: string;
  profiles?: ChatModelProfile[];
  download_hint?: string;
  files?: GgufFileInfo[];
  chat?: ModelRoleBlock;
  code?: ModelRoleBlock;
  same_model?: boolean;
  defaults?: { chat?: string; code?: string };
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
  bond?: "early" | "growing" | "attached" | string;
  inner_circle?: { name?: string; role?: string }[];
  updated_at?: string;
  style_ready?: boolean;
  style_samples?: number;
  speaker?: SpeakerGuardSummary;
};

export type ComputeSettings = {
  mode?: "cpu" | "gpu" | "hybrid" | string;
  gpu_layers?: number;
  resolved_n_gpu_layers?: number;
  hybrid_possible?: boolean;
  hybrid_hint?: string;
  llama_gpu_offload?: boolean;
  nvidia_detected?: boolean;
  note?: string;
  load?: {
    n_layer?: number | null;
    n_gpu_layers_requested?: number | null;
    n_gpu_layers_effective?: number | null;
    n_cpu_layers?: number | null;
    n_threads?: number | null;
    loaded?: boolean;
  };
};

export type StatusResponse = {
  ollama: boolean;
  llm?: LlmBackendInfo;
  model: string;
  vision_model?: string;
  vision?: {
    available?: boolean;
    backend?: string | null;
    filename?: string | null;
    mmproj?: string | null;
    handler?: string | null;
    label?: string | null;
    path?: string | null;
    download_hint?: string | null;
  };
  eyes: boolean;
  ears: boolean;
  pending_patch?: boolean;
  models?: string[];
  limits?: StatusLimits;
  approve_phrase?: string;
  user?: UserProfileSummary;
  compute?: ComputeSettings;
  chat_models?: ChatModelsStatus;
  model_roles?: ChatModelsStatus;
  pending_finetune?: boolean;
  finetune_approve_phrase?: string;
  finetune_reset_phrase?: string;
  pending_soft?: boolean;
  soft_approve_phrase?: string;
  soft_evolve_from_dialogue?: boolean;
  sensors_enabled?: boolean;
  finetune?: {
    state?: string;
    job_id?: string;
    generation?: number;
    phase?: string;
    error?: string;
    log?: string;
    result?: Record<string, unknown>;
    updated_at?: string;
    started_at?: string;
    finished_at?: string;
  };
  finetune_lineage?: {
    generation?: number;
    active_gguf?: string;
    active_checkpoint?: string;
  };
  news?: {
    sources?: NewsSources;
    items?: number;
  };
  proactive?: {
    today?: string;
    used?: number;
    max?: number;
    remaining?: number;
    last_rare_ping_at?: string | null;
  };
  chat_busy?: boolean;
  chat_pending?: {
    id?: string;
    kind?: string;
    phase?: string;
    label?: string;
    user_text?: string;
    started_at?: string;
    user_saved?: boolean;
  } | null;
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

export type ReplyContextItem = {
  role: "user" | "assistant";
  content: string;
  ts?: string | null;
};

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

export type FinetuneStatusResponse = {
  status?: {
    state?: string;
    job_id?: string;
    generation?: number;
    phase?: string;
    error?: string;
    log?: string;
    result?: Record<string, unknown>;
    updated_at?: string;
    started_at?: string;
    finished_at?: string;
  };
  pending?: {
    id?: string;
    generation?: number;
    pairs?: number;
    chat_pairs?: number;
    identity_pairs?: number;
    export_gguf_name?: string;
    base?: { kind?: string; hf_id?: string; path?: string };
    params?: Record<string, unknown>;
  } | null;
  lineage?: {
    generation?: number;
    active_gguf?: string;
    active_checkpoint?: string;
    history?: unknown[];
  };
  approve_phrase?: string;
  reset_phrase?: string;
  base_gguf?: string;
};

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

export type NewsIntervalOption = {
  value: string | number;
  label: string;
  minutes?: number | null;
};

export type NewsRssSource = {
  url: string;
  interval?: string | number;
};

export type NewsTelegramSource = {
  id: string;
  interval?: string | number;
};

export type NewsSources = {
  global_interval_min?: number | null;
  rss?: Array<string | NewsRssSource>;
  telegram?: Array<string | NewsTelegramSource>;
  last_fetch?: Record<string, string>;
  updated_at?: string;
};

export type NewsAutoStatus = {
  running?: boolean;
  phase?: string | null;
  message?: string | null;
  pending_after_chat?: boolean;
  due_count?: number;
  due?: unknown[];
  last_result?: {
    at?: string;
    added?: number;
    errors?: string[];
    error?: string;
  } | null;
  interval_options?: NewsIntervalOption[];
  source_interval_options?: NewsIntervalOption[];
};

export type NewsSourcesResponse = {
  sources?: NewsSources;
  items?: number;
  auto?: NewsAutoStatus;
};

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

export async function proactivePing() {
  const res = await fetch("/api/proactive/ping");
  return parseJson<{ message?: string }>(res);
}

export const FILE_ACCEPT =
  ".txt,.md,.markdown,.fb2,.xml,.djvu,.djv,.zip,.rar,.py,.js,.mjs,.cjs,.ts,.tsx,.jsx,.java,.go,.rs,.c,.cpp,.h,.hpp,.cs,.rb,.php,.swift,.kt,.sql,.sh,.ps1,.json,.yaml,.yml,.toml,.html,.css,.scss,.vue,.svelte,.lua,.dart";
