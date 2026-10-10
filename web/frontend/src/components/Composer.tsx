import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CloseIcon from "@mui/icons-material/Close";
import MicIcon from "@mui/icons-material/Mic";
import MicNoneIcon from "@mui/icons-material/MicNone";
import ReplyIcon from "@mui/icons-material/Reply";
import SendIcon from "@mui/icons-material/Send";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import InputBase from "@mui/material/InputBase";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { FILE_ACCEPT } from "../api";
import type { EarPhase } from "../hooks/useEarHold";
import type { Bubble } from "../types";

type Props = {
  disabled?: boolean;
  stagedFile: File | null;
  onStageFile: (file: File | null) => void;
  onSend: (message: string) => void;
  replyTo?: Bubble | null;
  onClearReply?: () => void;
  /** Уши включены — показать кнопку микрофона рядом с отправкой */
  earsOn?: boolean;
  earPhase?: EarPhase;
  onEarPointerDown?: (e: ReactPointerEvent<HTMLButtonElement>) => void;
  onEarPointerUp?: () => void;
};

function previewText(text: string, max = 100): string {
  const one = text.replace(/\s+/g, " ").trim();
  if (one.length <= max) return one;
  return `${one.slice(0, max - 1)}…`;
}

const actionBtnSx = {
  bgcolor: "#007BFF",
  color: "#fff",
  borderRadius: 2.5,
  "&:hover": { bgcolor: "#0056b3" },
  "&.Mui-disabled": { bgcolor: "#24332c", color: "text.secondary" },
} as const;

export function Composer({
  disabled,
  stagedFile,
  onStageFile,
  onSend,
  replyTo,
  onClearReply,
  earsOn = false,
  earPhase = "idle",
  onEarPointerDown,
  onEarPointerUp,
}: Props) {
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (replyTo) {
      inputRef.current?.focus();
    }
  }, [replyTo?.id]);

  const submit = () => {
    if (disabled) return;
    if (!stagedFile && !text.trim()) return;
    onSend(text.trim());
    setText("");
  };

  const earBusy =
    earPhase === "transcribing" || earPhase === "replying";
  const recording = earPhase === "recording";
  const micDisabled =
    Boolean(disabled && earPhase === "idle") || earBusy || !earsOn;

  const micTip = recording
    ? "Отпусти — закончить запись и распознать"
    : earPhase === "transcribing"
      ? "Распознаю речь…"
      : earPhase === "replying"
        ? "Думаю над ответом…"
        : "Зажми и говори, отпусти — распознаю и отвечу";

  return (
    <Box sx={{ borderTop: 1, borderColor: "divider", flexShrink: 0 }}>
      {replyTo && (
        <Box
          sx={{
            px: 1.5,
            pt: 1.25,
            display: "flex",
            alignItems: "flex-start",
            gap: 1,
          }}
        >
          <Box
            sx={{
              flex: 1,
              minWidth: 0,
              px: 1.25,
              py: 0.85,
              borderRadius: 2,
              borderLeft: 3,
              borderColor: "primary.main",
              bgcolor: "#16201b",
            }}
          >
            <Stack direction="row" spacing={0.75} sx={{ mb: 0.35, alignItems: "center" }}>
              <ReplyIcon sx={{ fontSize: 14, color: "primary.main" }} />
              <Typography
                variant="caption"
                sx={{ color: "primary.light", fontWeight: 700 }}
              >
                Ответ · {replyTo.who === "user" ? "ты" : "Зипка"}
              </Typography>
            </Stack>
            <Typography
              variant="caption"
              sx={{ color: "text.secondary", display: "block" }}
            >
              {previewText(replyTo.text)}
            </Typography>
          </Box>
          <IconButton
            size="small"
            onClick={() => onClearReply?.()}
            sx={{ color: "text.secondary", mt: 0.25 }}
            aria-label="Снять ответ"
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
      )}
      {stagedFile && (
        <Box sx={{ px: 1.5, pt: 1.25 }}>
          <Chip
            icon={<AttachFileIcon />}
            label={stagedFile.name}
            onDelete={() => onStageFile(null)}
            deleteIcon={<CloseIcon />}
            variant="outlined"
            sx={{ maxWidth: "100%" }}
          />
        </Box>
      )}
      <Stack
        direction="row"
        spacing={1}
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        sx={{ p: 1.5, alignItems: "flex-end" }}
      >
        <input
          ref={fileRef}
          type="file"
          accept={FILE_ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0] ?? null;
            e.target.value = "";
            if (file) onStageFile(file);
          }}
        />
        <Tooltip title="Прикрепить файл">
          <IconButton
            onClick={() => fileRef.current?.click()}
            disabled={disabled}
            sx={{
              border: 1,
              borderColor: "divider",
              borderRadius: 2.5,
              bgcolor: "#24332c",
            }}
          >
            <AttachFileIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Paper
          component="div"
          elevation={0}
          sx={{
            flex: 1,
            display: "flex",
            alignItems: "stretch",
            px: 1.5,
            py: 0.5,
            bgcolor: "#0f1613",
            border: 1,
            borderColor: "divider",
            borderRadius: 1.5,
          }}
        >
          <InputBase
            inputRef={inputRef}
            fullWidth
            multiline
            minRows={1}
            maxRows={6}
            placeholder={
              replyTo
                ? "Продолжить эту ветку… Enter — отправить"
                : earsOn
                  ? "Сообщение… или зажми микрофон"
                  : "Сообщение… Enter — отправить, Shift+Enter — новая строка"
            }
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            sx={{
              color: "text.primary",
              fontSize: "0.95rem",
              alignItems: "flex-start",
              "& textarea": { lineHeight: 1.45 },
            }}
          />
        </Paper>
        {earsOn ? (
          <Tooltip title={micTip} arrow>
            <span>
              <IconButton
                type="button"
                aria-label="Микрофон"
                disabled={micDisabled}
                onPointerDown={(e) => onEarPointerDown?.(e)}
                onPointerUp={onEarPointerUp}
                onPointerCancel={onEarPointerUp}
                onLostPointerCapture={onEarPointerUp}
                onContextMenu={(e) => e.preventDefault()}
                sx={{
                  ...actionBtnSx,
                  touchAction: "none",
                  userSelect: "none",
                  ...(recording
                    ? {
                        bgcolor: "#c45c5c",
                        animation: "zipka-mic-pulse 1.1s ease-in-out infinite",
                        "@keyframes zipka-mic-pulse": {
                          "0%, 100%": { filter: "brightness(1)" },
                          "50%": { filter: "brightness(1.15)" },
                        },
                        "&:hover": { bgcolor: "#b04e4e" },
                      }
                    : {}),
                }}
              >
                {recording ? (
                  <MicIcon fontSize="small" />
                ) : (
                  <MicNoneIcon fontSize="small" />
                )}
              </IconButton>
            </span>
          </Tooltip>
        ) : null}
        <IconButton
          type="submit"
          color="primary"
          aria-label="Отправить"
          disabled={disabled || (!stagedFile && !text.trim())}
          sx={actionBtnSx}
        >
          <SendIcon fontSize="small" />
        </IconButton>
      </Stack>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", px: 1.5, pb: 1, mt: -0.5 }}
      >
        {replyTo
          ? "Ответ подхватит эту ветку как приоритетный контекст"
          : earsOn
            ? "Микрофон: зажми и говори · текст = комментарий к файлу"
            : "Текст сообщения = комментарий к файлу"}
      </Typography>
    </Box>
  );
}
