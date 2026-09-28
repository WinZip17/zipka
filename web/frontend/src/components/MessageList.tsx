import { useEffect, useRef } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

export type Bubble = {
  id: string;
  who: "user" | "bot";
  text: string;
  at?: string | null;
};

type Props = {
  messages: Bubble[];
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
};

function formatMessageTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();

  const time = d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (sameDay) return time;

  const sameYear = d.getFullYear() === now.getFullYear();
  const date = d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  return `${date} ${time}`;
}

export function MessageList({ messages, hasMore, loadingOlder, onLoadOlder }: Props) {
  const logRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickBottom = useRef(true);
  const bootDone = useRef(false);

  useEffect(() => {
    bootDone.current = true;
  }, []);

  useEffect(() => {
    if (stickBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [messages]);

  return (
    <Box
      ref={logRef}
      onScroll={() => {
        const el = logRef.current;
        if (!el || !bootDone.current) return;
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        stickBottom.current = nearBottom;
        if (el.scrollTop <= 48) onLoadOlder();
      }}
      sx={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        overflowX: "hidden",
        p: 2,
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
        overscrollBehavior: "contain",
      }}
    >
      {hasMore && (
        <Chip
          size="small"
          label={loadingOlder ? "загрузка…" : "↑ прокрути выше за старыми"}
          sx={{ alignSelf: "center", opacity: loadingOlder ? 0.6 : 1 }}
        />
      )}
      {messages.map((m) => {
        const when = formatMessageTime(m.at);
        return (
          <Box
            key={m.id}
            sx={{
              maxWidth: "85%",
              alignSelf: m.who === "user" ? "flex-end" : "flex-start",
              px: 1.5,
              py: 1.25,
              borderRadius: 3.5,
              whiteSpace: "pre-wrap",
              lineHeight: 1.45,
              bgcolor: m.who === "user" ? "#2a4035" : "#1b2730",
              border: m.who === "bot" ? 1 : 0,
              borderColor: "divider",
              flexShrink: 0,
            }}
          >
            <Typography component="div" variant="body2" sx={{ color: "text.primary" }}>
              {m.text}
            </Typography>
            {when && (
              <Typography
                component="div"
                variant="caption"
                title={m.at ? new Date(m.at).toLocaleString("ru-RU") : undefined}
                sx={{
                  mt: 0.75,
                  display: "block",
                  textAlign: m.who === "user" ? "right" : "left",
                  color: "text.secondary",
                  opacity: 0.85,
                  fontSize: "0.7rem",
                  lineHeight: 1,
                }}
              >
                {when}
              </Typography>
            )}
          </Box>
        );
      })}
      <div ref={bottomRef} />
      {!messages.length && (
        <Stack sx={{ py: 6, opacity: 0.7, alignItems: "center" }}>
          <Typography color="text.secondary">История пуста — напиши Зипке</Typography>
        </Stack>
      )}
    </Box>
  );
}
