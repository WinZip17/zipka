import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  fetchHistory,
  fetchNewsAuto,
  fetchPending,
  fetchStatus,
  proactiveHello,
  proactivePing,
  sendChat,
  uploadBook,
} from "../api";
import { buildReplyChain, roleToWho, whoToRole } from "../chat/roles";
import { playReplySound, unlockReplySound } from "../notifySound";
import type { Bubble, StatusResponse } from "../types";

const PAGE_SIZE = 30;

export function useChatSession() {
  const idBase = useId();
  const seq = useRef(0);
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [pending, setPending] = useState<unknown>(null);
  const [stagedFile, setStagedFile] = useState<File | null>(null);
  const [archiveMember, setArchiveMember] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState<string | null>(null);
  const [newsThinking, setNewsThinking] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [oldestIndex, setOldestIndex] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [replyTo, setReplyTo] = useState<Bubble | null>(null);
  const loadingOlderRef = useRef(false);
  const hasMoreRef = useRef(false);
  const oldestRef = useRef<number | null>(null);
  const statusRef = useRef<StatusResponse | null>(null);
  /** Локальный in-flight запрос этой вкладки (не путать с server pending после F5). */
  const localRequestRef = useRef(false);
  const sawServerPendingRef = useRef(false);
  const messagesRef = useRef<Bubble[]>([]);
  const finetuneBusy = status?.finetune?.state === "running";

  const addBubble = useCallback(
    (
      text: string,
      who: "user" | "bot",
      at?: string | null,
      meta?: {
        replyToId?: string | null;
        replyTo?: Bubble["replyTo"];
      },
    ) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${idBase}-${++seq.current}`,
          who,
          text,
          at: at ?? new Date().toISOString(),
          replyToId: meta?.replyToId ?? null,
          replyTo: meta?.replyTo ?? null,
        },
      ]);
    },
    [idBase],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const [st, pend] = await Promise.all([fetchStatus(), fetchPending()]);
      setStatus(st);
      statusRef.current = st;
      setPending(pend.pending ?? null);
      return st;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    hasMoreRef.current = hasMore;
  }, [hasMore]);

  useEffect(() => {
    oldestRef.current = oldestIndex;
  }, [oldestIndex]);

  const loadInitialHistory = useCallback(async () => {
    try {
      const data = await fetchHistory({ limit: PAGE_SIZE });
      setHasMore(!!data.has_more);
      setOldestIndex(data.oldest_index);
      const mapped = (data.messages || []).map((m, i) => ({
        id: `${idBase}-h-${i}`,
        who: roleToWho(m.role),
        text: m.content,
        at: m.ts ?? null,
        replyTo: m.reply_to?.content
          ? {
              who: roleToWho(m.reply_to.role || "assistant"),
              text: m.reply_to.content,
            }
          : null,
      }));
      setMessages(mapped);
      return mapped;
    } catch {
      setHasMore(false);
      return [];
    }
  }, [idBase]);

  const syncChatPending = useCallback(
    async (
      st: StatusResponse | null | undefined,
      history?: { who: string }[],
    ) => {
      if (localRequestRef.current) {
        // Локальный запрос сам держит thinking; подтянем лейбл фазы с сервера
        const label = st?.chat_pending?.label;
        if (label) setThinking(label);
        return;
      }

      const rows = history ?? messagesRef.current;
      const last = rows.length ? rows[rows.length - 1] : null;
      const lastIsUser = last?.who === "user";
      const label = st?.chat_pending?.label || "Вникаю…";

      // Главный сигнал после F5: в истории есть вопрос без ответа
      if (lastIsUser) {
        sawServerPendingRef.current = true;
        setThinking(label);
        setBusy(true);
        return;
      }

      if (sawServerPendingRef.current) {
        sawServerPendingRef.current = false;
        setBusy(false);
        setThinking(null);
      }
    },
    [],
  );

  const onBusyFromPanel = useCallback((v: boolean) => {
    localRequestRef.current = v;
    setBusy(v);
  }, []);

  const loadOlderHistory = useCallback(async () => {
    if (
      !hasMoreRef.current ||
      loadingOlderRef.current ||
      oldestRef.current === null ||
      oldestRef.current <= 0
    ) {
      return;
    }
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    try {
      const data = await fetchHistory({ before: oldestRef.current, limit: PAGE_SIZE });
      setHasMore(!!data.has_more);
      setOldestIndex(data.oldest_index);
      const older = (data.messages || []).map((m, i) => ({
        id: `${idBase}-o-${oldestRef.current}-${i}`,
        who: roleToWho(m.role),
        text: m.content,
        at: m.ts ?? null,
        replyTo: m.reply_to?.content
          ? {
              who: roleToWho(m.reply_to.role || "assistant"),
              text: m.reply_to.content,
            }
          : null,
      }));
      setMessages((prev) => [...older, ...prev]);
    } catch {
      /* keep flags */
    } finally {
      loadingOlderRef.current = false;
      setLoadingOlder(false);
    }
  }, [idBase]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const hist = await loadInitialHistory();
      if (!alive) return;
      // Сразу, до status: если лента обрывается на вопросе — покажи «Вникаю…»
      if (hist.at(-1)?.who === "user") {
        sawServerPendingRef.current = true;
        setThinking("Вникаю…");
        setBusy(true);
      }
      const st = await refreshStatus();
      if (!alive) return;
      await syncChatPending(st, hist);
      try {
        if (hist.at(-1)?.who !== "user" && !st?.chat_pending) {
          const hello = await proactiveHello();
          if (alive && hello.message) addBubble(hello.message, "bot");
        }
      } catch {
        /* ignore */
      }
    })();

    const statusTimer = window.setInterval(async () => {
      const st = await refreshStatus();
      if (!alive) return;
      // Пока ждём ответ после F5 — подтягиваем историю, чтобы поймать появление реплики
      if (sawServerPendingRef.current && !localRequestRef.current) {
        const hist = await loadInitialHistory();
        if (!alive) return;
        await syncChatPending(st, hist);
      } else {
        await syncChatPending(st);
      }
    }, 2000);

    const newsTimer = window.setInterval(async () => {
      if (statusRef.current?.finetune?.state === "running") {
        setNewsThinking(null);
        return;
      }
      try {
        const auto = await fetchNewsAuto();
        setNewsThinking(
          auto.running && auto.message ? auto.message : null,
        );
      } catch {
        /* ignore */
      }
    }, 2500);
    const pingTimer = window.setInterval(async () => {
      if (statusRef.current?.finetune?.state === "running") return;
      if (statusRef.current?.chat_pending) return;
      try {
        const data = await proactivePing();
        if (data.message) addBubble(data.message, "bot");
        void refreshStatus();
      } catch {
        /* ignore */
      }
    }, 12 * 60 * 1000);
    return () => {
      alive = false;
      window.clearInterval(statusTimer);
      window.clearInterval(newsTimer);
      window.clearInterval(pingTimer);
    };
  }, [addBubble, loadInitialHistory, refreshStatus, syncChatPending]);

  const onSend = async (message: string) => {
    if (busy || statusRef.current?.finetune?.state === "running") return;
    if (statusRef.current?.chat_pending) return;
    localRequestRef.current = true;
    setBusy(true);
    unlockReplySound();
    const activeReply = replyTo;
    setReplyTo(null);
    try {
      if (stagedFile) {
        const file = stagedFile;
        setStagedFile(null);
        const label = message ? `${message}\n📎 ${file.name}` : `📎 ${file.name}`;
        addBubble(label, "user");
        setThinking("Изучаю…");
        try {
          const data = await uploadBook(
            file,
            archiveMember.trim() || null,
            message || null,
          );
          sawServerPendingRef.current = false;
          addBubble(data.reply || data.digest || "Готово", "bot");
          playReplySound();
          void refreshStatus();
        } catch (err) {
          sawServerPendingRef.current = false;
          addBubble(err instanceof Error ? err.message : String(err), "bot");
          playReplySound();
        }
        return;
      }
      const chain = activeReply
        ? buildReplyChain(messages, activeReply)
        : undefined;
      addBubble(message, "user", null, {
        replyToId: activeReply?.id ?? null,
        replyTo: activeReply
          ? { who: activeReply.who, text: activeReply.text }
          : null,
      });
      setThinking("Вникаю…");
      try {
        const data = await sendChat(message, {
          reply_to: activeReply
            ? {
                role: whoToRole(activeReply.who),
                content: activeReply.text,
                ts: activeReply.at ?? null,
              }
            : null,
          reply_chain: chain,
        });
        sawServerPendingRef.current = false;
        addBubble(data.reply || "(пустой ответ)", "bot");
        playReplySound();
        void refreshStatus();
      } catch (err) {
        sawServerPendingRef.current = false;
        addBubble(err instanceof Error ? err.message : String(err), "bot");
        playReplySound();
      }
    } finally {
      localRequestRef.current = false;
      if (!statusRef.current?.chat_pending) {
        setThinking(null);
        setBusy(false);
      }
    }
  };

  const resetChat = useCallback(() => {
    setMessages([]);
    setHasMore(false);
    setOldestIndex(null);
  }, []);

  return {
    messages,
    status,
    pending,
    stagedFile,
    setStagedFile,
    archiveMember,
    setArchiveMember,
    busy,
    thinking,
    setThinking,
    newsThinking,
    dropActive,
    setDropActive,
    hasMore,
    loadingOlder,
    replyTo,
    setReplyTo,
    finetuneBusy,
    addBubble,
    refreshStatus,
    loadOlderHistory,
    onBusyFromPanel,
    onSend,
    resetChat,
  };
}
