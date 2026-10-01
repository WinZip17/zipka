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
