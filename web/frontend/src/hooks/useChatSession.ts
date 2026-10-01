import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchHistory,
  proactivePing,
  sendChat,
  uploadBook,
} from "../api";
import { buildReplyChain, roleToWho, whoToRole } from "../chat/roles";
import { playReplySound, unlockReplySound } from "../notifySound";
import {
  fetchNewsAuto,
  fetchSessionSnapshot,
  queryKeys,
} from "../query/session";
import type { Bubble, StatusResponse } from "../types";

const PAGE_SIZE = 30;
const SESSION_POLL_MS = 2000;
const NEWS_POLL_MS = 2500;
/** Как часто спрашивать сервер «пора ли пинговать» (сам сервер ждёт 30м–3ч простоя). */
const PING_POLL_MS = 60 * 1000;

export function useChatSession() {
  const idBase = useId();
  const seq = useRef(0);
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [stagedFile, setStagedFile] = useState<File | null>(null);
  const [archiveMember, setArchiveMember] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState<string | null>(null);
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
  const pingInFlightRef = useRef(false);

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

  const sessionQuery = useQuery({
    queryKey: queryKeys.session,
    queryFn: fetchSessionSnapshot,
    refetchInterval: SESSION_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 1000,
  });

  const status = sessionQuery.data?.status ?? null;
  const pending = sessionQuery.data?.pending ?? null;
  const finetuneBusy = status?.finetune?.state === "running";

  const newsQuery = useQuery({
    queryKey: queryKeys.newsAuto,
    queryFn: fetchNewsAuto,
    refetchInterval: NEWS_POLL_MS,
    refetchIntervalInBackground: false,
    enabled: !finetuneBusy,
    staleTime: 1500,
  });

  const newsThinking =
    newsQuery.data?.running && newsQuery.data.message
      ? newsQuery.data.message
      : null;

  const refreshStatus = useCallback(async () => {
    try {
      const result = await queryClient.fetchQuery({
        queryKey: queryKeys.session,
        queryFn: fetchSessionSnapshot,
      });
      statusRef.current = result.status;
      return result.status;
    } catch {
      return null;
    }
  }, [queryClient]);

  useEffect(() => {
    hasMoreRef.current = hasMore;
  }, [hasMore]);

  useEffect(() => {
    oldestRef.current = oldestIndex;
  }, [oldestIndex]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

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
    (
      st: StatusResponse | null | undefined,
      history?: { who: string }[],
    ) => {
      // Локальный sendChat/upload ещё в полёте — только подтянуть лейбл фазы
      if (localRequestRef.current) {
        const label = st?.chat_pending?.label;
        if (label) setThinking(label);
        return;
      }

      const rows = history ?? messagesRef.current;
      const last = rows.length ? rows[rows.length - 1] : null;
      const lastIsUser = last?.who === "user";
      const label = st?.chat_pending?.label || "Вникаю…";

      // Ответ уже в ленте — UI свободен. Stale chat_pending из «запоздавшего»
      // status/pending не должен снова включать «Вникаю…».
      if (!lastIsUser) {
        sawServerPendingRef.current = false;
        setBusy(false);
        setThinking(null);
        return;
      }

      // Хвост истории — вопрос пользователя: ждём ответ (F5 / in-flight)
      sawServerPendingRef.current = true;
      setThinking(label);
      setBusy(true);
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
      const data = await fetchHistory({
        before: oldestRef.current,
        limit: PAGE_SIZE,
      });
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

  // Первичная загрузка истории (без мгновенного hello/ping)
  useEffect(() => {
    let alive = true;
    (async () => {
      const hist = await loadInitialHistory();
      if (!alive) return;
      if (hist.at(-1)?.who === "user") {
        sawServerPendingRef.current = true;
        setThinking("Вникаю…");
        setBusy(true);
      }
      const st = await refreshStatus();
      if (!alive) return;
      syncChatPending(st, hist);
    })();
    return () => {
      alive = false;
    };
  }, [loadInitialHistory, refreshStatus, syncChatPending]);

  // Реакция на обновления session (в т.ч. после F5, пока ждём ответ)
  const historySyncInFlightRef = useRef(false);
  const statusSyncGenRef = useRef(0);
  useEffect(() => {
    if (!status) return;
    const gen = ++statusSyncGenRef.current;
    let alive = true;
    (async () => {
      const waiting =
        !localRequestRef.current &&
        (Boolean(status.chat_pending || status.chat_busy) ||
          sawServerPendingRef.current ||
          messagesRef.current.at(-1)?.who === "user");

      if (waiting) {
        if (historySyncInFlightRef.current) {
          if (gen === statusSyncGenRef.current) syncChatPending(status);
          return;
        }
        historySyncInFlightRef.current = true;
        try {
          const hist = await loadInitialHistory();
          if (!alive || gen !== statusSyncGenRef.current) return;
          syncChatPending(status, hist);
        } finally {
          historySyncInFlightRef.current = false;
        }
      } else if (gen === statusSyncGenRef.current) {
        syncChatPending(status);
      }
    })();
    return () => {
      alive = false;
    };
  }, [status, loadInitialHistory, syncChatPending]);

  // Редкий ping: сервер сам ждёт 30м–3ч простоя после сообщения пользователя
  useEffect(() => {
    const id = window.setInterval(() => {
      const st = statusRef.current;
      if (st?.finetune?.state === "running") return;
      if (st?.chat_pending) return;
      const nextAt = st?.proactive?.next_rare_ping_at;
      if (!nextAt) return; // ещё не планировали — не дёргаем API
      const due = Date.parse(nextAt);
      if (!Number.isNaN(due) && Date.now() < due) return;
      if (pingInFlightRef.current) return;
      pingInFlightRef.current = true;
      void proactivePing()
        .then((data) => {
          if (data.message) {
            addBubble(data.message, "bot");
            void refreshStatus();
          }
        })
        .catch(() => {
          /* ignore */
        })
        .finally(() => {
          pingInFlightRef.current = false;
        });
    }, PING_POLL_MS);
    return () => window.clearInterval(id);
  }, [addBubble, refreshStatus]);

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
        const label = message
          ? `${message}\n📎 ${file.name}`
          : `📎 ${file.name}`;
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
      // Локальный ход закончен — всегда снимаем блокировку UI.
      // Stale chat_pending в кэше status больше не должен оставлять «Вникаю…».
      localRequestRef.current = false;
      sawServerPendingRef.current = false;
      setThinking(null);
      setBusy(false);
      void queryClient.cancelQueries({ queryKey: queryKeys.session }).then(() =>
        refreshStatus().then((st) => {
          syncChatPending(st);
        }),
      );
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
