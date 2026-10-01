import { useEffect, useRef } from "react";
import ReplyIcon from "@mui/icons-material/Reply";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { Bubble } from "../types";

type Props = {
  messages: Bubble[];
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  thinking?: string | null;
  onReply?: (bubble: Bubble) => void;
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

function previewText(text: string, max = 90): string {
  const one = text.replace(/\s+/g, " ").trim();
  if (one.length <= max) return one;
  return `${one.slice(0, max - 1)}…`;
}

export function MessageList({
  messages,
  hasMore,
  loadingOlder,
  onLoadOlder,
  thinking,
  onReply,
}: Props) {
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
  }, [messages, thinking]);

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
              borderRadius: 0.5,
              whiteSpace: "pre-wrap",
              lineHeight: 1.45,
              bgcolor: m.who === "user" ? "#2a4035" : "#1b2730",
              border: m.who === "bot" ? 1 : 0,
              borderColor: "divider",
              flexShrink: 0,
              position: "relative",
              "&:hover .zipka-reply-btn": { opacity: 1 },
            }}
          >
            {m.replyTo && (
              <Box
                sx={{
                  mb: 1,
                  px: 1,
                  py: 0.75,
                  borderRadius: 0.5,
                  borderLeft: 3,
                  borderColor: "primary.main",
                  bgcolor: "rgba(0,0,0,0.22)",
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    color: "primary.light",
                    fontWeight: 700,
                    mb: 0.25,
                  }}
                >
                  {m.replyTo.who === "user" ? "ты" : "Зипка"}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: "text.secondary", display: "block" }}
                >
                  {previewText(m.replyTo.text, 120)}
                </Typography>
              </Box>
            )}
            <Typography component="div" variant="body2" sx={{ color: "text.primary" }}>
              {m.text}
            </Typography>
            <Box
              sx={{
                mt: 0.75,
                display: "flex",
                alignItems: "center",
                justifyContent: m.who === "user" ? "flex-end" : "flex-start",
                gap: 0.5,
              }}
            >
              {when && (
                <Typography
                  component="div"
                  variant="caption"
                  title={m.at ? new Date(m.at).toLocaleString("ru-RU") : undefined}
                  sx={{
                    color: "text.secondary",
                    opacity: 0.85,
                    fontSize: "0.7rem",
                    lineHeight: 1,
                  }}
                >
                  {when}
                </Typography>
              )}
              {onReply && (
                <Tooltip title="Ответить">
                  <IconButton
                    className="zipka-reply-btn"
                    size="small"
                    onClick={() => onReply(m)}
                    sx={{
                      opacity: { xs: 0.85, sm: 0.35 },
                      p: 0.35,
                      color: "text.secondary",
                      "&:hover": { color: "primary.main", bgcolor: "transparent" },
                    }}
                  >
                    <ReplyIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          </Box>
        );
      })}
      {thinking && (
        <Box
          sx={{
            maxWidth: "85%",
            alignSelf: "flex-start",
            px: 1.5,
            py: 1.25,
            borderRadius: 0.5,
            bgcolor: "#1b2730",
            border: 1,
            borderColor: "divider",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 1,
          }}
        >
          <Box
            sx={{
              display: "flex",
              gap: 0.5,
              "& span": {
                width: 6,
                height: 6,
                borderRadius: "50%",
                bgcolor: "primary.main",
                animation: "zipkaPulse 1.2s ease-in-out infinite",
              },
              "& span:nth-of-type(2)": { animationDelay: "0.2s" },
              "& span:nth-of-type(3)": { animationDelay: "0.4s" },
              "@keyframes zipkaPulse": {
                "0%, 80%, 100%": { opacity: 0.25, transform: "scale(0.85)" },
                "40%": { opacity: 1, transform: "scale(1)" },
              },
            }}
          >
            <span />
            <span />
            <span />
          </Box>
          <Typography
            variant="body2"
            sx={{ color: "text.secondary", fontStyle: "italic" }}
          >
            {thinking}
          </Typography>
        </Box>
      )}
      <div ref={bottomRef} />
      {!messages.length && !thinking && (
        <Stack sx={{ py: 6, opacity: 0.7, alignItems: "center" }}>
          <Typography color="text.secondary">История пуста — напиши Зипке</Typography>
        </Stack>
      )}
    </Box>
  );
}
