import type { Bubble } from "../components/MessageList";

export function roleToWho(role: string): "user" | "bot" {
  return role === "user" ? "user" : "bot";
}

export function whoToRole(who: "user" | "bot"): "user" | "assistant" {
  return who === "user" ? "user" : "assistant";
}

export function buildReplyChain(
  messages: Bubble[],
  target: Bubble,
): { role: "user" | "assistant"; content: string; ts?: string | null }[] {
  const byId = new Map(messages.map((m) => [m.id, m]));
  const ancestors: Bubble[] = [];
  let cur: Bubble | undefined = target;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    ancestors.unshift(cur);
    cur = cur.replyToId ? byId.get(cur.replyToId) : undefined;
  }

  // + пара сообщений сразу после цели (продолжение той же ветки во времени)
  const idx = messages.findIndex((m) => m.id === target.id);
  const follow: Bubble[] = [];
  if (idx >= 0) {
    for (let i = idx + 1; i < Math.min(messages.length, idx + 5); i += 1) {
      const m = messages[i];
      if (seen.has(m.id)) continue;
      // если это уже чужой reply на другое — всё равно даём хронологический хвост
      follow.push(m);
      seen.add(m.id);
    }
  }

  return [...ancestors, ...follow].map((m) => ({
    role: whoToRole(m.who),
    content: m.text,
    ts: m.at ?? null,
  }));
}
