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
