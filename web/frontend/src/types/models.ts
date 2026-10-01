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
