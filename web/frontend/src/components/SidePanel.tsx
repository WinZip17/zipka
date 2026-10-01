import { useEffect, useRef, useState } from "react";
import type { FormEvent, PointerEvent } from "react";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import {
  FILE_ACCEPT,
  approvePatch,
  earsAction,
  eyesAction,
  learn,
  proactivePing,
  sendChat,
} from "../api";
import { playReplySound } from "../notifySound";
import type { StatusResponse } from "../types";
import { InfoDialog } from "./sidepanel/InfoDialog";
import { SettingsDialog } from "./sidepanel/SettingsDialog";
import { headerBtnSx } from "./sidepanel/styles";
import { SectionTitle } from "./sidepanel/utils";

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

export function SidePanel({
  status,
  pending,
  busy: chatBusy,
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
  const [settingsTab, setSettingsTab] = useState(0);
  const [infoOpen, setInfoOpen] = useState(false);
  const [path, setPath] = useState("");
  const [comment, setComment] = useState("");
  const [mode, setMode] = useState("auto");
  const [edits, setEdits] = useState(false);
  const [learnQ, setLearnQ] = useState("");
  const [sensorsFeature, setSensorsFeature] = useState(false);
  const [earPhase, setEarPhase] = useState<
    "idle" | "recording" | "transcribing" | "replying"
  >("idle");
  const earSessionRef = useRef(false);
  const earServerStartedRef = useRef(false);
  const earBusyRef = useRef(false);

  const finetuneRunning = status?.finetune?.state === "running";
  // Пока идёт дообучение — блокируем остальные действия в панели
  const busy = chatBusy || finetuneRunning;

  useEffect(() => {
    if (typeof status?.sensors_enabled === "boolean") {
      setSensorsFeature(status.sensors_enabled);
    }
  }, [status?.sensors_enabled]);

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
    try {
      const data = await earsAction(earsOn ? "off" : "on");
      if (data.message) onBubble(data.message, "bot");
    } catch (err) {
      onBubble(err instanceof Error ? err.message : String(err), "bot");
    }
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

  const stopEarSession = async () => {
    if (earBusyRef.current) return;
    earBusyRef.current = true;
    setEarPhase("transcribing");
    onBusy(true);
    onThinking("Распознаю речь…");
    try {
      const data = await earsAction("listen_stop");
      if (data.heard) onBubble(`(уши) ${data.heard}`, "user");
      if (data.skipped_chat) {
        if (data.heard === "(слишком коротко)") {
          onBubble("Слишком коротко — зажми «Слушать» и говори дольше.", "bot");
        }
        return;
      }
      setEarPhase("replying");
      onThinking("Вникаю…");
      if (data.comment) onBubble(data.comment, "bot");
      if (data.reply) {
        onBubble(data.reply, "bot");
        playReplySound();
      } else if (data.detail) onBubble(String(data.detail), "bot");
      else if (data.message) onBubble(data.message, "bot");
      onRefresh();
    } catch (err) {
      onBubble(err instanceof Error ? err.message : String(err), "bot");
    } finally {
      earBusyRef.current = false;
      earServerStartedRef.current = false;
      setEarPhase("idle");
      onThinking(null);
      onBusy(false);
    }
  };

  const startEarHold = async (e: PointerEvent<HTMLButtonElement>) => {
    e.preventDefault();
    if (busy || !earsOn || earSessionRef.current || earBusyRef.current) return;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    earSessionRef.current = true;
    earServerStartedRef.current = false;
    setEarPhase("recording");
    onThinking("● Запись… говори");
    try {
      await earsAction("listen_start");
      earServerStartedRef.current = true;
    } catch (err) {
      earSessionRef.current = false;
      earServerStartedRef.current = false;
      setEarPhase("idle");
      onThinking(null);
      onBubble(err instanceof Error ? err.message : String(err), "bot");
      return;
    }
    // уже отпустили, пока поднимали микрофон
    if (!earSessionRef.current) {
      await stopEarSession();
    }
  };

  const endEarHold = () => {
    if (!earSessionRef.current) return;
    earSessionRef.current = false;
    if (earServerStartedRef.current) {
      void stopEarSession();
    }
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
        playReplySound();
        onRefresh();
      } catch (err) {
        onBubble(err instanceof Error ? err.message : String(err), "bot");
        playReplySound();
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

  const runForcePing = async () => {
    if (busy) return;
    await withBusy("Думаю…", async () => {
      try {
        const data = await proactivePing(true);
        if (data.message) {
          onBubble(data.message, "bot");
          playReplySound();
        } else if (data.skipped === "no_materials") {
          onBubble(
            "Пинг пропущен: нет заметок обучения (книга/код/сеть/новости).",
            "bot",
          );
        } else {
          onBubble("Пинг не сработал (лимит или пустой ответ).", "bot");
        }
        onRefresh();
      } catch (err) {
        onBubble(err instanceof Error ? err.message : String(err), "bot");
      }
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

  const openInfo = () => {
    onRefresh();
    setInfoOpen(true);
  };

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

      {sensorsFeature ? (
        <>
          <SectionTitle>Сенсоры</SectionTitle>
          <Stack
            direction="row"
            spacing={0.75}
            useFlexGap
            sx={{ mb: 1, flexWrap: "wrap" }}
          >
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
                [
                  "snap",
                  "Камера",
                  "Сделать снимок с веб-камеры и описать, что видно",
                ],
                [
                  "screen",
                  "Экран",
                  "Снять весь монитор и описать содержимое экрана",
                ],
                [
                  "window",
                  "Окно",
                  "Снять активное окно приложения и описать его",
                ],
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
          <Stack
            direction="row"
            spacing={0.75}
            useFlexGap
            sx={{ flexWrap: "wrap" }}
          >
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
              title={
                earPhase === "recording"
                  ? "Отпусти — закончить запись и распознать"
                  : earPhase === "transcribing"
                    ? "Распознаю речь…"
                    : earPhase === "replying"
                      ? "Думаю над ответом…"
                      : "Зажми и говори, отпусти — распознаю и отвечу"
              }
              arrow
              enterDelay={400}
            >
              <span>
                <Button
                  size="small"
                  variant={earPhase === "recording" ? "contained" : "outlined"}
                  disabled={
                    (busy && earPhase === "idle") ||
                    !earsOn ||
                    earPhase === "transcribing" ||
                    earPhase === "replying"
                  }
                  onPointerDown={(e) => void startEarHold(e)}
                  onPointerUp={endEarHold}
                  onPointerCancel={endEarHold}
                  onLostPointerCapture={endEarHold}
                  onContextMenu={(e) => e.preventDefault()}
                  sx={{
                    ...sensorBtnSx(earPhase === "recording"),
                    ...(earPhase === "recording"
                      ? {
                          bgcolor: "#c45c5c",
                          borderColor: "#e57373",
                          color: "#fff",
                          animation: "zipka-ear-pulse 1.1s ease-in-out infinite",
                          "@keyframes zipka-ear-pulse": {
                            "0%, 100%": { filter: "brightness(1)" },
                            "50%": { filter: "brightness(1.15)" },
                          },
                          "&:hover": {
                            bgcolor: "#b04e4e",
                            borderColor: "#e57373",
                          },
                        }
                      : {}),
                    touchAction: "none",
                    userSelect: "none",
                  }}
                >
                  {earPhase === "recording"
                    ? "● Запись…"
                    : earPhase === "transcribing"
                      ? "Распознаю…"
                      : earPhase === "replying"
                        ? "Думаю…"
                        : "Слушать"}
                </Button>
              </span>
            </Tooltip>
          </Stack>
        </>
      ) : null}

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
      <Tooltip
        title="Форс study-ping: перечитает случайный материал обучения и задаст уточняющие вопросы (мимо таймера простоя)"
        arrow
        enterDelay={400}
      >
        <span>
          <Button
            size="small"
            fullWidth
            variant="outlined"
            disabled={busy}
            onClick={() => void runForcePing()}
            sx={{ mt: 1 }}
          >
            Запустить пинг
          </Button>
        </span>
      </Tooltip>

      <InfoDialog
        open={infoOpen}
        onClose={() => setInfoOpen(false)}
        status={status}
        sensorsFeature={sensorsFeature}
        eyesOn={eyesOn}
        earsOn={earsOn}
      />

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        settingsTab={settingsTab}
        onSettingsTabChange={setSettingsTab}
        status={status}
        chatBusy={chatBusy}
        sensorsFeature={sensorsFeature}
        onSensorsFeatureChange={setSensorsFeature}
        onBubble={onBubble}
        onThinking={onThinking}
        onRefresh={onRefresh}
        onResetChat={onResetChat}
      />
    </Box>
  );
}
