import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import {
  FILE_ACCEPT,
  approvePatch,
  earsAction,
  eyesAction,
  learn,
  resetInfo,
  resetLearning,
  sendChat,
  setChatModel,
  setCompute,
  type StatusResponse,
} from "../api";

type Props = {
  status: StatusResponse | null;
  pending: unknown;
  busy: boolean;
  eyesOn: boolean;
  earsOn: boolean;
  archiveMember: string;
  onArchiveMember: (value: string) => void;
  onBubble: (text: string, who: "user" | "bot") => void;
  onThinking: (hint: string | null) => void;
  onBusy: (busy: boolean) => void;
  onRefresh: () => void;
  onResetChat: () => void;
  onStageFile: (file: File) => void;
};

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="subtitle2"
      color="text.secondary"
      sx={{ mt: 1.5, mb: 1, fontWeight: 700, letterSpacing: 0.04 }}
    >
      {children}
    </Typography>
  );
}

function InfoBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography
        variant="subtitle2"
        color="text.secondary"
        sx={{ mb: 0.75, fontWeight: 700 }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function InfoLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 1,
        py: 0.35,
      }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>
        {label}
      </Typography>
      <Typography
        variant="body2"
        sx={{ textAlign: "right", color: "text.primary", wordBreak: "break-word" }}
      >
        {value}
      </Typography>
    </Stack>
  );
}

const dialogPaperSx = {
  bgcolor: "#17201c",
  backgroundImage: "none",
  border: 1,
  borderColor: "divider",
};

const headerBtnSx = {
  border: 1,
  borderColor: "divider",
  borderRadius: 2,
  color: "text.secondary",
  bgcolor: "#24332c",
};

export function SidePanel({
  status,
  pending,
  busy,
  eyesOn,
  earsOn,
  archiveMember,
  onArchiveMember,
  onBubble,
  onThinking,
  onBusy,
  onRefresh,
  onResetChat,
  onStageFile,
}: Props) {
  const sideFileRef = useRef<HTMLInputElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [path, setPath] = useState("");
  const [comment, setComment] = useState("");
  const [mode, setMode] = useState("auto");
  const [edits, setEdits] = useState(false);
  const [learnQ, setLearnQ] = useState("");
  const [computeMode, setComputeMode] = useState<"cpu" | "gpu" | "hybrid">("cpu");
  const [gpuLayers, setGpuLayers] = useState(24);
  const [computeBusy, setComputeBusy] = useState(false);
  const [computeMsg, setComputeMsg] = useState<string | null>(null);
  const [chatModelId, setChatModelId] = useState("pathfinder");
  const [chatModelBusy, setChatModelBusy] = useState(false);
  const [chatModelMsg, setChatModelMsg] = useState<string | null>(null);

  useEffect(() => {
    const c = status?.compute;
    if (!c) return;
    const m = (c.mode || "cpu") as "cpu" | "gpu" | "hybrid";
    if (m === "cpu" || m === "gpu" || m === "hybrid") setComputeMode(m);
    if (typeof c.gpu_layers === "number") setGpuLayers(c.gpu_layers);
  }, [status?.compute]);

  useEffect(() => {
    const id = status?.chat_models?.active_id;
    if (id) setChatModelId(id);
  }, [status?.chat_models?.active_id]);

  const applyCompute = async () => {
    setComputeBusy(true);
    setComputeMsg(null);
    try {
      const data = await setCompute(
        computeMode,
        computeMode === "hybrid" ? gpuLayers : null,
      );
      const note = data.compute?.note;
      setComputeMsg(
        `Режим: ${data.compute?.mode || computeMode}` +
          (data.compute?.resolved_n_gpu_layers !== undefined
            ? ` (слоёв GPU: ${data.compute.resolved_n_gpu_layers})`
            : "") +
          (note ? `\n${note}` : ""),
      );
      onRefresh();
    } catch (err) {
      setComputeMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setComputeBusy(false);
    }
  };

  const applyChatModel = async () => {
    setChatModelBusy(true);
    setChatModelMsg(null);
    try {
      const data = await setChatModel(chatModelId);
      const label =
        data.chat_models?.active_label ||
        data.llm?.chat_model_label ||
        chatModelId;
      setChatModelMsg(`Активна: ${label}`);
      onRefresh();
    } catch (err) {
      setChatModelMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setChatModelBusy(false);
    }
  };

  const withBusy = async (hint: string, fn: () => Promise<void>) => {
    if (busy) return;
    onBusy(true);
    onThinking(hint);
    try {
      await fn();
    } finally {
      onThinking(null);
      onBusy(false);
    }
  };

  const sensorBtnSx = (active: boolean) => ({
    color: active ? "primary.contrastText" : "text.primary",
    borderColor: active ? "primary.main" : "divider",
    bgcolor: active ? "primary.main" : "#24332c",
    "&:hover": {
      bgcolor: active ? "primary.main" : "#2c3d34",
      borderColor: active ? "primary.main" : "divider",
      filter: active ? "brightness(1.05)" : undefined,
    },
    // busy/disabled не должен съедать индикатор «сенсор включён»
    "&.Mui-disabled": active
      ? {
          color: "primary.contrastText",
          borderColor: "primary.main",
          bgcolor: "primary.main",
          opacity: 0.9,
        }
      : {
          color: "text.disabled",
          borderColor: "divider",
          bgcolor: "#1a2420",
          opacity: 0.65,
        },
  });

  const toggleEyes = async () => {
    try {
      const data = await eyesAction(eyesOn ? "off" : "on");
      if (data.message) onBubble(data.message, "bot");
    } catch (err) {
      onBubble(err instanceof Error ? err.message : String(err), "bot");
    }
    onRefresh();
  };

  const toggleEars = async () => {
    await earsAction(earsOn ? "off" : "on");
    onRefresh();
  };

  const eyeCapture = async (action: string) => {
    await withBusy("Смотрю…", async () => {
      const data = await eyesAction(action);
      if (data.description) onBubble(data.description, "bot");
      else if (data.detail) onBubble(data.detail, "bot");
      else if (data.message) onBubble(data.message, "bot");
      if (data.comment) onBubble(data.comment, "bot");
      onRefresh();
    });
  };

  const earListen = async () => {
    await withBusy("Слушаю…", async () => {
      const data = await earsAction("listen");
      if (data.heard) onBubble(`(уши) ${data.heard}`, "user");
      if (data.comment) onBubble(data.comment, "bot");
      if (data.reply) onBubble(data.reply, "bot");
      else if (data.detail) onBubble(data.detail, "bot");
      else if (data.message) onBubble(data.message, "bot");
      onRefresh();
    });
  };

  const onStudy = async (e: FormEvent) => {
    e.preventDefault();
    if (!path.trim()) return;
    let message = `изучи папку ${path.trim()}`;
    if (archiveMember.trim()) message += ` внутри ${archiveMember.trim()}`;
    if (mode && mode !== "auto") message += ` режим: ${mode}`;
    if (comment.trim()) message += ` комментарий: ${comment.trim()}`;
    if (edits) message += ` предложи правки`;
    onBubble(message, "user");
    await withBusy("Изучаю…", async () => {
      try {
        const data = await sendChat(message);
        onBubble(data.reply || "(пустой ответ)", "bot");
        onRefresh();
      } catch (err) {
        onBubble(err instanceof Error ? err.message : String(err), "bot");
      }
    });
  };

  const onLearn = async (e: FormEvent) => {
    e.preventDefault();
    if (!learnQ.trim()) return;
    await withBusy("Учусь…", async () => {
      const data = await learn(learnQ.trim());
      onBubble(data.summary || JSON.stringify(data), "bot");
      setLearnQ("");
      onRefresh();
    });
  };

  const onApprove = async () => {
    await withBusy("Применяю…", async () => {
      try {
        const data = await approvePatch();
        let msg = `Патч применён: ${data.id}`;
        if (data.frontend_rebuild) msg += `\nСборка UI: ${data.frontend_rebuild}`;
        onBubble(msg, "bot");
      } catch (err) {
        onBubble(err instanceof Error ? err.message : "Нет патча", "bot");
      }
      onRefresh();
    });
  };

  const onReset = async () => {
    const info = await resetInfo();
    const phrase = info.confirm_phrase || "подтверждаю сброс обучения";
    const ok = window.confirm(
      "Сбросить ВСЁ обучение?\n\nБудут удалены: чат, заметки, цели, книги, снимки, патчи, persona.yaml.\n\nЭто необратимо.",
    );
    if (!ok) {
      onBubble("Сброс отменён.", "bot");
      return;
    }
    const typed = window.prompt(`Для подтверждения введи фразу:\n${phrase}`, "");
    if (typed === null) {
      onBubble("Сброс отменён.", "bot");
      return;
    }
    try {
      const data = await resetLearning(typed);
      setSettingsOpen(false);
      onResetChat();
      onBubble(data.message || "Обучение сброшено.", "bot");
      onRefresh();
    } catch (err) {
      onBubble(err instanceof Error ? err.message : "Сброс не выполнен", "bot");
    }
  };

  const openInfo = () => {
    onRefresh();
    setInfoOpen(true);
  };

  const llmBackend = status?.llm?.backend || (status?.ollama ? "ollama" : "—");
  const llmOk =
    status?.llm?.available ??
    (llmBackend === "gguf" ? Boolean(status?.model) : Boolean(status?.ollama));
  const statusLine = status
    ? `${llmBackend}: ${llmOk ? "OK" : "offline"} · ${status.model} · eyes ${
        status.eyes ? "on" : "off"
      } · ears ${status.ears ? "on" : "off"}`
    : "статус загружается…";

  const approvePhrase = status?.approve_phrase || "разрешаю правку кода";
  const bookLimit = status?.limits?.max_book_human || "…";
  const ramAvail = status?.limits?.ram_available_human || "н/д";
  const ping = status?.proactive;
  const models = status?.models || [];

  return (
    <Box
      sx={{
        p: 2,
        overflowY: "auto",
        overscrollBehavior: "contain",
        height: "100%",
      }}
    >
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", justifyContent: "space-between", mb: 0.5 }}
      >
        <Typography
          variant="subtitle2"
          color="text.secondary"
          sx={{ fontWeight: 700, letterSpacing: 0.04, m: 0 }}
        >
          Панель
        </Typography>
        <Stack direction="row" spacing={0.75}>
          <Tooltip title="Информация" arrow>
            <IconButton
              size="small"
              aria-label="Информация"
              onClick={openInfo}
              sx={headerBtnSx}
            >
              <InfoOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Настройки" arrow>
            <IconButton
              size="small"
              aria-label="Настройки"
              onClick={() => setSettingsOpen(true)}
              sx={headerBtnSx}
            >
              <SettingsIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      <SectionTitle>Сенсоры</SectionTitle>
      <Stack direction="row" spacing={0.75} useFlexGap sx={{ mb: 1, flexWrap: "wrap" }}>
        <Tooltip
          title={
            eyesOn
              ? "Выключить глаза — камера освободится"
              : "Включить глаза: откроется веб-камера"
          }
          arrow
          enterDelay={400}
        >
          <span>
            <Button
              size="small"
              variant={eyesOn ? "contained" : "outlined"}
              disabled={busy}
              onClick={() => void toggleEyes()}
              sx={sensorBtnSx(eyesOn)}
            >
              Глаза
            </Button>
          </span>
        </Tooltip>
        {(
          [
            ["snap", "Камера", "Сделать снимок с веб-камеры и описать, что видно"],
            ["screen", "Экран", "Снять весь монитор и описать содержимое экрана"],
            ["window", "Окно", "Снять активное окно приложения и описать его"],
          ] as const
        ).map(([action, label, tip]) => (
          <Tooltip key={action} title={tip} arrow enterDelay={400}>
            <span>
              <Button
                size="small"
                variant="outlined"
                disabled={busy}
                onClick={() => void eyeCapture(action)}
                sx={sensorBtnSx(false)}
              >
                {label}
              </Button>
            </span>
          </Tooltip>
        ))}
      </Stack>
      <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: "wrap" }}>
        <Tooltip
          title={
            earsOn
              ? "Выключить уши — микрофон не используется"
              : "Включить уши: Зипка может слушать"
          }
          arrow
          enterDelay={400}
        >
          <span>
            <Button
              size="small"
              variant={earsOn ? "contained" : "outlined"}
              disabled={busy}
              onClick={() => void toggleEars()}
              sx={sensorBtnSx(earsOn)}
            >
              Уши
            </Button>
          </span>
        </Tooltip>
        <Tooltip
          title="Записать несколько секунд с микрофона, распознать речь и ответить"
          arrow
          enterDelay={400}
        >
          <span>
            <Button
              size="small"
              variant="outlined"
              disabled={busy}
              onClick={() => void earListen()}
              sx={sensorBtnSx(false)}
            >
              Слушать
            </Button>
          </span>
        </Tooltip>
      </Stack>

      <SectionTitle>Патч</SectionTitle>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1,
          bgcolor: "#0f1613",
          borderRadius: 2,
          border: 1,
          borderColor: "divider",
          color: "text.secondary",
          fontSize: "0.75rem",
          maxHeight: 140,
          overflow: "auto",
        }}
      >
        {pending ? JSON.stringify(pending, null, 2) : "нет ожидающего патча"}
      </Box>
      <Button
        fullWidth
        color="warning"
        variant="contained"
        disabled={busy || !pending}
        onClick={() => void onApprove()}
        sx={{ mt: 1 }}
      >
        Разрешаю правку кода
      </Button>

      <SectionTitle>Книга / код / папка</SectionTitle>
      <Stack component="form" spacing={1} onSubmit={(e) => void onStudy(e)}>
        <TextField
          size="small"
          label="Путь"
          placeholder="C:\path\project"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <TextField
          size="small"
          label="Файл в архиве"
          placeholder="опционально"
          value={archiveMember}
          onChange={(e) => onArchiveMember(e.target.value)}
        />
        <TextField
          size="small"
          label="Фокус"
          placeholder="комментарий (опц.)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <FormControl size="small">
          <InputLabel id="book-mode-label">Режим</InputLabel>
          <Select
            labelId="book-mode-label"
            label="Режим"
            value={mode}
            onChange={(e) => setMode(String(e.target.value))}
          >
            <MenuItem value="auto">auto (книги+код)</MenuItem>
            <MenuItem value="books">только книги</MenuItem>
            <MenuItem value="code">только код</MenuItem>
          </Select>
        </FormControl>
        <FormControlLabel
          control={<Checkbox checked={edits} onChange={(e) => setEdits(e.target.checked)} />}
          label="предложить правки после изучения"
          sx={{ color: "text.secondary", "& .MuiFormControlLabel-label": { fontSize: "0.85rem" } }}
        />
        <Button type="submit" variant="contained" disabled={busy || !path.trim()}>
          Изучить по пути
        </Button>
      </Stack>

      <Alert
        severity="info"
        icon={<UploadFileIcon fontSize="inherit" />}
        sx={{
          mt: 1.5,
          bgcolor: "transparent",
          border: "1px dashed",
          borderColor: "divider",
          color: "text.secondary",
          cursor: "pointer",
          "& .MuiAlert-message": { width: "100%" },
        }}
        onClick={() => sideFileRef.current?.click()}
      >
        Или выбери файл — он прикрепится к сообщению в чате
        <input
          ref={sideFileRef}
          type="file"
          accept={FILE_ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onStageFile(file);
          }}
        />
      </Alert>

      <Divider sx={{ my: 2, borderColor: "divider" }} />

      <SectionTitle>Обучение</SectionTitle>
      <Stack component="form" direction="row" spacing={1} onSubmit={(e) => void onLearn(e)}>
        <TextField
          size="small"
          fullWidth
          placeholder="URL или тема"
          value={learnQ}
          onChange={(e) => setLearnQ(e.target.value)}
        />
        <Button type="submit" variant="contained" disabled={busy || !learnQ.trim()}>
          Learn
        </Button>
      </Stack>

      <Dialog
        open={infoOpen}
        onClose={() => setInfoOpen(false)}
        fullWidth
        maxWidth="sm"
        slotProps={{ paper: { sx: dialogPaperSx } }}
      >
        <DialogTitle sx={{ fontFamily: '"Manrope", sans-serif', fontWeight: 700 }}>
          Информация
        </DialogTitle>
        <DialogContent>
          <InfoBlock title="Состояние">
            <Box
              sx={{
                p: 1.25,
                borderRadius: 2,
                border: 1,
                borderColor: "divider",
                bgcolor: "#0f1613",
                fontFamily: '"IBM Plex Sans", monospace',
                fontSize: "0.85rem",
                color: "text.secondary",
                lineHeight: 1.5,
              }}
            >
              {statusLine}
            </Box>
          </InfoBlock>

          <InfoBlock title="Собеседник">
            <InfoLine label="Имя" value={status?.user?.name || "ещё не узнала"} />
            {status?.user?.how_to_address ? (
              <InfoLine label="Обращение" value={status.user.how_to_address} />
            ) : null}
            <InfoLine
              label="Привязанность"
              value={
                status?.user?.bond === "attached"
                  ? "привязана"
                  : status?.user?.bond === "growing"
                    ? "узнаёт"
                    : "раннее знакомство"
              }
            />
            {(status?.user?.inner_circle || []).length > 0 ? (
              <InfoLine
                label="Свои"
                value={(status?.user?.inner_circle || [])
                  .map((p) =>
                    p.role && p.role !== "trusted"
                      ? `${p.name} (${p.role === "primary" ? "основной" : p.role})`
                      : p.name || "",
                  )
                  .filter(Boolean)
                  .join(", ")}
              />
            ) : null}
            <InfoLine
              label="Настроение"
              value={
                status?.user?.mood
                  ? status.user.mood_previous
                    ? `${status.user.mood} (было: ${status.user.mood_previous})`
                    : status.user.mood
                  : "—"
              }
            />
            <InfoLine
              label="Тип личности"
              value={status?.user?.personality_type || "—"}
            />
            <InfoLine
              label="Характер"
              value={(status?.user?.character || []).join(", ") || "—"}
            />
            <InfoLine
              label="Особенности"
              value={(status?.user?.peculiarities || []).join(", ") || "—"}
            />
            <InfoLine label="Любит" value={(status?.user?.likes || []).join(", ") || "—"} />
            <InfoLine
              label="Не любит"
              value={(status?.user?.dislikes || []).join(", ") || "—"}
            />
            <InfoLine
              label="Время"
              value={(status?.user?.time_habits || []).join(", ") || "—"}
            />
            <InfoLine
              label="Состояние"
              value={
                [status?.user?.current_state, status?.user?.energy && `энергия: ${status.user.energy}`]
                  .filter(Boolean)
                  .join("; ") || "—"
              }
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75 }}>
              Наблюдений: {status?.user?.evidence_count ?? 0}
              {status?.user?.facts_count ? ` · фактов: ${status.user.facts_count}` : ""}
              {" · стиль: "}
              {status?.user?.style_ready
                ? `готов (${status?.user?.style_samples ?? 0})`
                : `учу (${status?.user?.style_samples ?? 0}/${8})`}
              {" · "}профиль в data/memory/user_profile.json
            </Typography>
            {status?.user?.speaker?.alert ? (
              <Typography
                variant="caption"
                sx={{ display: "block", mt: 0.75, color: "warning.main" }}
              >
                Смена собеседника? уверенность{" "}
                {Math.round(Number(status.user.speaker.confidence || 0) * 100)}%
                {status.user.speaker.signals?.length
                  ? ` — ${status.user.speaker.signals.slice(0, 3).join("; ")}`
                  : ""}
                {" · "}защищает своих
              </Typography>
            ) : status?.user?.style_ready ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                Охрана стиля: активна (срабатывает только при высокой уверенности)
              </Typography>
            ) : null}
          </InfoBlock>

          <InfoBlock title="Лимиты">
            <InfoLine label="Макс. размер файла" value={bookLimit} />
            <InfoLine label="Свободная RAM" value={ramAvail} />
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
              Лимит ~12% свободной памяти (32–512 МБ), либо ZIPKA_MAX_BOOK_BYTES в .env
            </Typography>
          </InfoBlock>

          <InfoBlock title="Модель">
            <InfoLine
              label="Бэкенд"
              value={
                llmBackend === "gguf"
                  ? `GGUF (${llmOk ? "готов" : "нужен llama-cpp-python"})`
                  : llmBackend === "ollama"
                    ? `Ollama (${status?.ollama ? "онлайн" : "офлайн"})`
                    : String(llmBackend)
              }
            />
            <InfoLine
              label="Профиль чата"
              value={
                status?.chat_models?.active_label ||
                status?.llm?.chat_model_label ||
                status?.chat_models?.active_id ||
                "—"
              }
            />
            <InfoLine label="Чат" value={status?.model || "—"} />
            {llmBackend === "gguf" && status?.llm?.model_path ? (
              <InfoLine label="Файл" value={status.llm.model_path} />
            ) : null}
            {(status?.chat_models?.profiles || []).length > 0 ? (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mt: 0.75 }}
              >
                {(status?.chat_models?.profiles || [])
                  .map(
                    (p) =>
                      `${p.present ? "✓" : "·"} ${p.label}${p.active ? " ←" : ""}`,
                  )
                  .join(" · ")}
              </Typography>
            ) : null}
            {llmBackend !== "gguf" ? (
              <InfoLine label="Vision" value={status?.vision_model || status?.model || "—"} />
            ) : (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                Vision/глаза в GGUF-режиме пока через Ollama
              </Typography>
            )}
            {models.length > 0 && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mt: 0.75 }}
              >
                Файлы: {models.slice(0, 8).join(", ")}
                {models.length > 8 ? "…" : ""}
              </Typography>
            )}
          </InfoBlock>

          <InfoBlock title="Сенсоры">
            <InfoLine label="Глаза" value={eyesOn ? "вкл" : "выкл"} />
            <InfoLine label="Уши" value={earsOn ? "вкл" : "выкл"} />
          </InfoBlock>

          <InfoBlock title="Патчи кода">
            <InfoLine label="Ожидает" value={status?.pending_patch ? "да" : "нет"} />
            <InfoLine label="Фраза approve" value={`«${approvePhrase}»`} />
          </InfoBlock>

          <InfoBlock title="Проактивность">
            <InfoLine
              label="Пинги сегодня"
              value={
                ping
                  ? `${ping.used ?? 0} / ${ping.max ?? 3} (осталось ${ping.remaining ?? "—"})`
                  : "—"
              }
            />
            <Typography variant="caption" color="text.secondary">
              Приветствие — один раз в день. Редкие пинги — не чаще 3 раз в сутки.
            </Typography>
          </InfoBlock>

          <InfoBlock title="Как пользоваться">
            <Typography variant="body2" color="text.secondary" component="div">
              <Box component="ul" sx={{ m: 0, pl: 2.2 }}>
                <li>К сообщению можно прикрепить файл (+) или drag-and-drop</li>
                <li>Форматы: txt, md, fb2, djvu, zip/rar, код (.py, .ts, …)</li>
                <li>DJVU со сканом без OCR текста не даст</li>
                <li>Изучение папки — форма справа или команда в чате</li>
                <li>Правки кода только после фразы approve или кнопки «Разрешаю…»</li>
              </Box>
            </Typography>
          </InfoBlock>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setInfoOpen(false)} sx={{ color: "text.secondary" }}>
            Закрыть
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        fullWidth
        maxWidth="xs"
        slotProps={{ paper: { sx: dialogPaperSx } }}
      >
        <DialogTitle sx={{ fontFamily: '"Manrope", sans-serif', fontWeight: 700 }}>
          Настройки
        </DialogTitle>
        <DialogContent>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 700 }}>
            Модель чата
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
            Pathfinder — личность. Qwen2.5 — запасной чат / инструкции. Скачай GGUF в{" "}
            <code>data/models</code>, затем переключи здесь.
          </Typography>
          <FormControl fullWidth size="small" sx={{ mb: 1.25 }}>
            <InputLabel id="chat-model-label">Профиль</InputLabel>
            <Select
              labelId="chat-model-label"
              label="Профиль"
              value={chatModelId}
              onChange={(e) => setChatModelId(String(e.target.value))}
            >
              {(status?.chat_models?.profiles || [
                { id: "pathfinder", label: "Pathfinder RP 12B RU", present: false },
                { id: "qwen25", label: "Qwen2.5-7B-Instruct Q5_K_M", present: false },
              ]).map((p) => (
                <MenuItem key={p.id} value={p.id} disabled={p.present === false}>
                  {p.present === false ? "· " : "✓ "}
                  {p.label}
                  {p.blurb ? ` — ${p.blurb}` : ""}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {chatModelMsg && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
            >
              {chatModelMsg}
            </Typography>
          )}
          <Button
            fullWidth
            variant="contained"
            disabled={busy || chatModelBusy}
            onClick={() => void applyChatModel()}
            sx={{ mb: 2.5 }}
          >
            {chatModelBusy ? "Гружу модель…" : "Применить модель чата"}
          </Button>

          <Divider sx={{ mb: 2 }} />

          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 700 }}>
            Модель: CPU / GPU
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
            Hybrid делит слои: часть на видеокарте, остальное на процессоре. Pathfinder ≈40
            слоёв — при 24 на GPU CPU почти не видно в диспетчере (GPU делает ~60%). Для
            заметной нагрузки на CPU поставь 8–16. Режим GPU = все слои на карте.
          </Typography>
          <ToggleButtonGroup
            exclusive
            fullWidth
            size="small"
            value={computeMode}
            onChange={(_e, v) => {
              if (v) setComputeMode(v);
            }}
            sx={{ mb: 1.5 }}
          >
            <ToggleButton value="cpu">CPU</ToggleButton>
            <ToggleButton value="gpu">GPU</ToggleButton>
            <ToggleButton value="hybrid">Hybrid</ToggleButton>
          </ToggleButtonGroup>
          {computeMode === "hybrid" && (
            <Box sx={{ px: 0.5, mb: 1.5 }}>
              <Typography variant="caption" color="text.secondary">
                Слоёв на GPU: {gpuLayers}
                {status?.compute?.load?.n_layer
                  ? ` / ${status.compute.load.n_layer} у модели`
                  : " (Pathfinder ≈40)"}
                {" · "}меньше число = больше CPU
              </Typography>
              <Slider
                size="small"
                min={1}
                max={Math.max(40, Number(status?.compute?.load?.n_layer) || 40)}
                value={gpuLayers}
                onChange={(_e, v) => setGpuLayers(Array.isArray(v) ? v[0] : v)}
                valueLabelDisplay="auto"
              />
            </Box>
          )}
          {status?.compute?.note && (
            <Alert severity={status.compute.llama_gpu_offload ? "success" : "info"} sx={{ mb: 1.5 }}>
              {status.compute.note}
            </Alert>
          )}
          {status?.compute?.load?.n_cpu_layers != null && (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
              Сейчас загружено: GPU{" "}
              {status.compute.load.n_gpu_layers_effective ?? "—"} / CPU{" "}
              {status.compute.load.n_cpu_layers}
              {status.compute.load.n_threads
                ? ` · потоков CPU: ${status.compute.load.n_threads}`
                : ""}
            </Typography>
          )}
          {computeMsg && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
            >
              {computeMsg}
            </Typography>
          )}
          <Button
            fullWidth
            variant="contained"
            disabled={busy || computeBusy}
            onClick={() => void applyCompute()}
            sx={{ mb: 2.5 }}
          >
            {computeBusy ? "Применяю…" : "Применить compute"}
          </Button>

          <Divider sx={{ mb: 2 }} />

          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 700 }}>
            Данные
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Полный сброс чата, заметок, целей, книг, снимков, патчей и persona.yaml. Действие
            необратимо.
          </Typography>
          <Button
            fullWidth
            color="error"
            variant="contained"
            disabled={busy}
            onClick={() => void onReset()}
            sx={{ bgcolor: "#5a1f1f", "&:hover": { bgcolor: "#6e2828" } }}
          >
            Сброс обучения
          </Button>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setSettingsOpen(false)} sx={{ color: "text.secondary" }}>
            Закрыть
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
