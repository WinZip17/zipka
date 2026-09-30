import { useCallback, useEffect, useId, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  fetchHistory,
  fetchNewsAuto,
  fetchPending,
  fetchStatus,
  proactiveHello,
  proactivePing,
  sendChat,
  uploadBook,
  type StatusResponse,
} from "./api";
import { Composer } from "./components/Composer";
import { MessageList, type Bubble } from "./components/MessageList";
import { SidePanel } from "./components/SidePanel";
import { playReplySound, unlockReplySound } from "./notifySound";

const PAGE_SIZE = 30;

function roleToWho(role: string): "user" | "bot" {
  return role === "user" ? "user" : "bot";
}

function whoToRole(who: "user" | "bot"): "user" | "assistant" {
  return who === "user" ? "user" : "assistant";
}

function buildReplyChain(
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

export default function App() {
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
  const finetuneBusy =
    status?.finetune?.state === "running";

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
    } catch {
      /* ignore */
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
      setMessages(
        (data.messages || []).map((m, i) => ({
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
        })),
      );
    } catch {
      setHasMore(false);
    }
  }, [idBase]);

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
    let alive = true;
    (async () => {
      await loadInitialHistory();
      if (!alive) return;
      await refreshStatus();
      try {
        const hello = await proactiveHello();
        if (alive && hello.message) addBubble(hello.message, "bot");
      } catch {
        /* ignore */
      }
    })();
    const statusTimer = window.setInterval(() => void refreshStatus(), 15000);
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
  }, [addBubble, loadInitialHistory, refreshStatus]);

  const onSend = async (message: string) => {
    if (busy || statusRef.current?.finetune?.state === "running") return;
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
        setThinking("Читаю…");
        try {
          const data = await uploadBook(
            file,
            archiveMember.trim() || null,
            message || null,
          );
          addBubble(data.reply || data.digest || "Готово", "bot");
          playReplySound();
          void refreshStatus();
        } catch (err) {
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
        addBubble(data.reply || "(пустой ответ)", "bot");
        playReplySound();
        void refreshStatus();
      } catch (err) {
        addBubble(err instanceof Error ? err.message : String(err), "bot");
        playReplySound();
      }
    } finally {
      setThinking(null);
      setBusy(false);
    }
  };

  return (
    <Box
      sx={{
        maxWidth: 1100,
        mx: "auto",
        height: "100%",
        p: { xs: 1.5, sm: 2 },
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        sx={{ mb: 1.5, flexShrink: 0, alignItems: "center" }}
      >
        <Box
          sx={{
            width: 44,
            height: 44,
            borderRadius: 3,
            display: "grid",
            placeItems: "center",
            background: "linear-gradient(145deg, #d9ff8a, #7ec8a3)",
            color: "#102018",
            fontWeight: 800,
            fontSize: "1.2rem",
            fontFamily: '"Manrope", sans-serif',
          }}
        >
          Z
        </Box>
        <Box>
          <Typography variant="h1" sx={{ fontSize: "1.55rem", m: 0 }}>
            Зипка
          </Typography>
        </Box>
      </Stack>

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1.5fr 0.9fr" },
          gap: 2,
        }}
      >
        <Paper
          elevation={0}
          onDragOver={(e) => {
            e.preventDefault();
            setDropActive(true);
          }}
          onDragLeave={() => setDropActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDropActive(false);
            const file = e.dataTransfer.files?.[0];
            if (file) setStagedFile(file);
          }}
          sx={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            height: { xs: "min(70vh, 640px)", md: "100%" },
            border: 1,
            borderColor: dropActive ? "primary.main" : "divider",
            outline: dropActive ? "2px dashed" : "none",
            outlineColor: "primary.main",
            outlineOffset: -4,
          }}
        >
          <MessageList
            messages={messages}
            hasMore={hasMore}
            loadingOlder={loadingOlder}
            onLoadOlder={() => void loadOlderHistory()}
            thinking={
              finetuneBusy
                ? "Идёт дообучение…"
                : thinking || (!busy ? newsThinking : null)
            }
            onReply={(b) => setReplyTo(b)}
          />
          <Composer
            disabled={busy || finetuneBusy}
            stagedFile={stagedFile}
            onStageFile={setStagedFile}
            onSend={(msg) => void onSend(msg)}
            replyTo={replyTo}
            onClearReply={() => setReplyTo(null)}
          />
        </Paper>

        <Paper
          elevation={0}
          sx={{
            border: 1,
            borderColor: "divider",
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          <SidePanel
            status={status}
            pending={pending}
            busy={busy}
            eyesOn={!!status?.eyes}
            earsOn={!!status?.ears}
            archiveMember={archiveMember}
            onArchiveMember={setArchiveMember}
            onBubble={addBubble}
            onThinking={setThinking}
            onBusy={setBusy}
            onRefresh={() => void refreshStatus()}
            onResetChat={() => {
              setMessages([]);
              setHasMore(false);
              setOldestIndex(null);
            }}
            onStageFile={setStagedFile}
          />
        </Paper>
      </Box>
    </Box>
  );
}
