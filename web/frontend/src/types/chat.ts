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

export type PendingResponse = {
  pending: unknown;
  approve_phrase?: string;
};

export type ReplyContextItem = {
  role: "user" | "assistant";
  content: string;
  ts?: string | null;
};

export type Bubble = {
  id: string;
  who: "user" | "bot";
  text: string;
  at?: string | null;
  replyToId?: string | null;
  replyTo?: {
    who: "user" | "bot";
    text: string;
  } | null;
};
