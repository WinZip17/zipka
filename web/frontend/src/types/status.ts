import type { ChatModelsStatus, ComputeSettings, LlmBackendInfo } from "./models";
import type { NewsSources } from "./news";
import type { UserProfileSummary } from "./user";

export type StatusLimits = {
  max_book_bytes?: number;
  max_book_human?: string;
  ram_available_bytes?: number | null;
  ram_available_human?: string | null;
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
    next_rare_ping_at?: string | null;
    last_user_activity_at?: string | null;
    idle_min_sec?: number;
    idle_max_sec?: number;
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
