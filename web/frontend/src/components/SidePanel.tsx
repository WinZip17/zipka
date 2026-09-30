import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import Alert from "@mui/material/Alert";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import {
  FILE_ACCEPT,
  abortFinetune,
  addNewsSource,
  approvePatch,
  earsAction,
  eyesAction,
  fetchFinetuneStatus,
  fetchNewsSources,
  ingestNews,
  learn,
  proposeFinetune,
  resetInfo,
  resetLearning,
  saveNewsSources,
  sendChat,
  setCompute,
  setModels,
  setNewsSchedule,
  setSoftEvolveDialogue,
  startFinetune,
  type FinetuneStatusResponse,
  type NewsIntervalOption,
  type NewsRssSource,
  type NewsTelegramSource,
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

function intervalSelectValue(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "off";
  return String(raw);
}

function parseIntervalChoice(value: string): string | number {
  if (value === "off" || value === "global") return value;
  const n = Number(value);
  return Number.isFinite(n) ? n : "global";
}

function formatElapsedHms(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

function parseUtcMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
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
  const [computeMode, setComputeMode] = useState<"cpu" | "gpu" | "hybrid">("cpu");
  const [gpuLayers, setGpuLayers] = useState(24);
  const [computeBusy, setComputeBusy] = useState(false);
  const [computeMsg, setComputeMsg] = useState<string | null>(null);
  const [chatGguf, setChatGguf] = useState("");
  const [codeGguf, setCodeGguf] = useState("");
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsMsg, setModelsMsg] = useState<string | null>(null);
  const [softDialogue, setSoftDialogue] = useState(false);
  const [softDialogueBusy, setSoftDialogueBusy] = useState(false);
  const [softDialogueMsg, setSoftDialogueMsg] = useState<string | null>(null);
  const [finetuneBusy, setFinetuneBusy] = useState(false);
  const [finetuneMsg, setFinetuneMsg] = useState<string | null>(null);
  const [finetuneInfo, setFinetuneInfo] = useState<FinetuneStatusResponse | null>(
    null,
  );
  const [newsRss, setNewsRss] = useState("");
  const [newsTg, setNewsTg] = useState("");
  const [newsRssList, setNewsRssList] = useState<NewsRssSource[]>([]);
  const [newsTgList, setNewsTgList] = useState<NewsTelegramSource[]>([]);
  const [newsGlobalInterval, setNewsGlobalInterval] = useState("off");
  const [newsIntervalOptions, setNewsIntervalOptions] = useState<
    NewsIntervalOption[]
  >([
    { value: "off", label: "выкл" },
    { value: 60, label: "1ч" },
    { value: 120, label: "2ч" },
    { value: 180, label: "3ч" },
    { value: 240, label: "4ч" },
    { value: 360, label: "6ч" },
    { value: 720, label: "12ч" },
    { value: 1440, label: "1д" },
  ]);
  const [newsSourceIntervalOptions, setNewsSourceIntervalOptions] = useState<
    NewsIntervalOption[]
  >([{ value: "global", label: "как глобально" }, { value: "off", label: "выкл" }]);
  const [newsItems, setNewsItems] = useState(0);
  const [newsBusy, setNewsBusy] = useState(false);
  const [newsMsg, setNewsMsg] = useState<string | null>(null);
  const [finetuneNowMs, setFinetuneNowMs] = useState(() => Date.now());

  const finetuneRunning =
    finetuneInfo?.status?.state === "running" ||
    status?.finetune?.state === "running";
  // Пока идёт дообучение — блокируем остальные действия в панели
  const busy = chatBusy || finetuneRunning;
  const finetuneStartedMs = parseUtcMs(
    finetuneInfo?.status?.started_at || status?.finetune?.started_at,
  );
  const finetuneFinishedMs = parseUtcMs(
    finetuneInfo?.status?.finished_at || status?.finetune?.finished_at,
  );
  // Таймер не скрываем после конца — замирает на finished_at / updated_at
  const finetuneEndMs = finetuneRunning
    ? finetuneNowMs
    : (finetuneFinishedMs ??
      parseUtcMs(
        finetuneInfo?.status?.updated_at || status?.finetune?.updated_at,
      ) ??
      finetuneNowMs);
  const finetuneElapsed =
    finetuneStartedMs != null
      ? formatElapsedHms(Math.max(0, finetuneEndMs - finetuneStartedMs))
      : null;

  useEffect(() => {
    const c = status?.compute;
    if (!c) return;
    const m = (c.mode || "cpu") as "cpu" | "gpu" | "hybrid";
    if (m === "cpu" || m === "gpu" || m === "hybrid") setComputeMode(m);
    if (typeof c.gpu_layers === "number") setGpuLayers(c.gpu_layers);
  }, [status?.compute]);

  useEffect(() => {
    if (typeof status?.soft_evolve_from_dialogue === "boolean") {
      setSoftDialogue(status.soft_evolve_from_dialogue);
    }
  }, [status?.soft_evolve_from_dialogue]);

  useEffect(() => {
    const roles = status?.chat_models || status?.model_roles;
    const chat = roles?.chat?.filename || roles?.active_id || roles?.defaults?.chat;
    const code = roles?.code?.filename || roles?.defaults?.code;
    if (chat) setChatGguf(chat);
    if (code) setCodeGguf(code);
  }, [
    status?.chat_models?.chat?.filename,
    status?.chat_models?.code?.filename,
    status?.chat_models?.active_id,
    status?.model_roles?.chat?.filename,
    status?.model_roles?.code?.filename,
  ]);

  const refreshFinetune = async () => {
    try {
      const data = await fetchFinetuneStatus();
      setFinetuneInfo(data);
      return data;
    } catch (err) {
      setFinetuneMsg(err instanceof Error ? err.message : String(err));
      return null;
    }
  };

  const refreshNews = async () => {
    try {
      const data = await fetchNewsSources();
      const rss = (data.sources?.rss || []).map((item) =>
        typeof item === "string"
          ? { url: item, interval: "global" as const }
          : { url: item.url, interval: item.interval ?? "global" },
      );
      const tg = (data.sources?.telegram || []).map((item) =>
        typeof item === "string"
          ? { id: item, interval: "global" as const }
          : { id: item.id, interval: item.interval ?? "global" },
      );
      setNewsRssList(rss);
      setNewsTgList(tg);
      setNewsGlobalInterval(
        intervalSelectValue(data.sources?.global_interval_min ?? "off"),
      );
      setNewsItems(data.items || 0);
      if (data.auto?.interval_options?.length) {
        setNewsIntervalOptions(data.auto.interval_options);
      }
      if (data.auto?.source_interval_options?.length) {
        setNewsSourceIntervalOptions(data.auto.source_interval_options);
      }
      return data;
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
      return null;
    }
  };

  useEffect(() => {
    if (!settingsOpen) return;
    void refreshFinetune();
    void refreshNews();
  }, [settingsOpen]);

  useEffect(() => {
    if (!settingsOpen) return;
    const state = finetuneInfo?.status?.state;
    if (state !== "running" && state !== "succeeded_pending_apply") return;
    const id = window.setInterval(() => {
      void refreshFinetune().then(() => onRefresh());
    }, 5000);
    return () => window.clearInterval(id);
  }, [settingsOpen, finetuneInfo?.status?.state, onRefresh]);

  useEffect(() => {
    if (!finetuneRunning || finetuneStartedMs == null) return;
    setFinetuneNowMs(Date.now());
    const id = window.setInterval(() => setFinetuneNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [finetuneRunning, finetuneStartedMs]);

  useEffect(() => {
    if (!finetuneRunning) return;
    setSettingsOpen(true);
    setSettingsTab(2);
  }, [finetuneRunning]);

  const onProposeFinetune = async () => {
    setFinetuneBusy(true);
    setFinetuneMsg(null);
    try {
      const data = await proposeFinetune();
      setFinetuneMsg(data.message || "Заявка на дообучение подготовлена.");
      await refreshFinetune();
      onRefresh();
    } catch (err) {
      setFinetuneMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setFinetuneBusy(false);
    }
  };

  const onStartFinetune = async () => {
    const phrase =
      finetuneInfo?.approve_phrase ||
      status?.finetune_approve_phrase ||
      "разрешаю дообучение";
    if (
      !window.confirm(
        `Запустить LoRA-дообучение?\nНужна фраза «${phrase}».\nПроцесс долгий и нагружает GPU/CPU.`,
      )
    ) {
      return;
    }
    setFinetuneBusy(true);
    setFinetuneMsg(null);
    try {
      const data = await startFinetune();
      setFinetuneMsg(data.message || `Запущено: ${data.job_id || ""}`);
      setSettingsTab(2);
      setSettingsOpen(true);
      await refreshFinetune();
      onRefresh();
    } catch (err) {
      setFinetuneMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setFinetuneBusy(false);
    }
  };

  const onAbortFinetune = async () => {
    if (
      !window.confirm(
        "Сбросить / прервать дообучение? Зависший статус «running» тоже снимется, ошибки очистятся.",
      )
    ) {
      return;
    }
    setFinetuneBusy(true);
    setFinetuneMsg(null);
    try {
      const data = await abortFinetune();
      await refreshFinetune();
      setFinetuneMsg(
        data.ok === false
          ? data.message || "Ошибка сброса"
          : data.message || "Сброшено.",
      );
      onRefresh();
    } catch (err) {
      setFinetuneMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setFinetuneBusy(false);
    }
  };

  const onAddRss = async () => {
    const url = newsRss.trim();
    if (!url) return;
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      await addNewsSource({ rss: url });
      setNewsRss("");
      await refreshNews();
      onRefresh();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onAddTg = async () => {
    const ch = newsTg.trim();
    if (!ch) return;
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      await addNewsSource({ telegram: ch });
      setNewsTg("");
      await refreshNews();
      onRefresh();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onRemoveRss = async (url: string) => {
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      const next = newsRssList.filter((u) => u.url !== url);
      await saveNewsSources({ rss: next, telegram: newsTgList });
      await refreshNews();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onRemoveTg = async (ch: string) => {
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      const next = newsTgList.filter((c) => c.id !== ch);
      await saveNewsSources({ rss: newsRssList, telegram: next });
      await refreshNews();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onGlobalInterval = async (value: string) => {
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      setNewsGlobalInterval(value);
      await setNewsSchedule({
        global_interval_min: value === "off" ? "off" : parseIntervalChoice(value),
      });
      await refreshNews();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onRssInterval = async (url: string, value: string) => {
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      await setNewsSchedule({
        rss: url,
        interval: parseIntervalChoice(value),
      });
      await refreshNews();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onTgInterval = async (ch: string, value: string) => {
    setNewsBusy(true);
    setNewsMsg(null);
    try {
      await setNewsSchedule({
        telegram: ch,
        interval: parseIntervalChoice(value),
      });
      await refreshNews();
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
    }
  };

  const onIngestNews = async () => {
    setNewsBusy(true);
    setNewsMsg(null);
    onThinking("Читаю новости…");
    try {
      const data = await ingestNews();
      const errs = data.errors?.length
        ? `\nОшибки: ${data.errors.slice(0, 3).join("; ")}`
        : "";
      setNewsMsg(`+${data.added ?? 0} выдержек${errs}`);
      await refreshNews();
      onRefresh();
      onBubble(
        `Обновила новости: +${data.added ?? 0} выдержек.` +
          (data.items?.[0]
            ? `\nПример: ${data.items[0].source}: ${data.items[0].title}`
            : ""),
        "bot",
      );
    } catch (err) {
      setNewsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setNewsBusy(false);
      onThinking(null);
    }
  };

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

  const applySoftDialogue = async (enabled: boolean) => {
    setSoftDialogueBusy(true);
    setSoftDialogueMsg(null);
    setSoftDialogue(enabled);
    try {
      const data = await setSoftEvolveDialogue(enabled);
      setSoftDialogue(Boolean(data.soft_evolve_from_dialogue));
      setSoftDialogueMsg(
        data.soft_evolve_from_dialogue
          ? "Soft-evolve из диалога включён (предложения ждут «запомни это»)."
          : "Soft-evolve из диалога выключен.",
      );
      onRefresh();
    } catch (err) {
      setSoftDialogue(!enabled);
      setSoftDialogueMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setSoftDialogueBusy(false);
    }
  };

  const applyModels = async () => {
    setModelsBusy(true);
    setModelsMsg(null);
    try {
      const data = await setModels({
        chat_gguf: chatGguf || undefined,
        code_gguf: codeGguf || undefined,
      });
      const roles = data.chat_models || data.models;
      const chatLabel = roles?.chat?.label || chatGguf;
      const codeLabel = roles?.code?.label || codeGguf;
      const same = roles?.same_model || chatGguf === codeGguf;
      setModelsMsg(
        same
          ? `Одна модель на чат и кодинг: ${chatLabel}`
          : `Чат: ${chatLabel}\nКодинг: ${codeLabel}`,
      );
      onRefresh();
    } catch (err) {
      setModelsMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setModelsBusy(false);
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
              label="Чат"
              value={
                status?.chat_models?.chat?.label ||
                status?.chat_models?.active_label ||
                status?.chat_models?.chat?.filename ||
                status?.model ||
                "—"
              }
            />
            <InfoLine
              label="Кодинг"
              value={
                status?.chat_models?.code?.label ||
                status?.chat_models?.code?.filename ||
                "—"
              }
            />
            {status?.chat_models?.same_model ? (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mt: 0.5 }}
              >
                Одна GGUF на обе роли (экономия VRAM)
              </Typography>
            ) : null}
            {llmBackend === "gguf" && status?.llm?.model_path ? (
              <InfoLine label="Файл чата" value={status.llm.model_path} />
            ) : null}
            {(status?.chat_models?.files || []).length > 0 ? (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mt: 0.75 }}
              >
                {(status?.chat_models?.files || [])
                  .map((f) => `✓ ${f.label || f.filename}`)
                  .join(" · ")}
              </Typography>
            ) : null}
            {llmBackend !== "gguf" ? (
              <InfoLine label="Vision" value={status?.vision_model || status?.model || "—"} />
            ) : (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                Vision:{" "}
                {status?.vision?.available
                  ? `${status.vision.label || status.vision.filename} (локальный GGUF)`
                  : status?.vision?.download_hint
                    ? `нет — ${status.vision.download_hint}`
                    : "нет локального mmproj; запасной путь — Ollama"}
              </Typography>
            )}
            {Array.isArray(models) && models.length > 0 && (
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
                <li>Ссылки: «Прочитай https://…» — скачает статью и сделает выжимку</li>
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
        onClose={() => {
          if (finetuneRunning) return;
          setSettingsOpen(false);
        }}
        fullWidth
        maxWidth="sm"
        slotProps={{
          paper: {
            sx: {
              ...dialogPaperSx,
              maxHeight: "min(88vh, 760px)",
              display: "flex",
              flexDirection: "column",
            },
          },
        }}
      >
        <DialogTitle
          sx={{
            fontFamily: '"Manrope", sans-serif',
            fontWeight: 700,
            pb: 0.5,
          }}
        >
          Настройки
          {finetuneRunning ? (
            <Typography
              component="span"
              variant="caption"
              color="warning.main"
              sx={{ display: "block", fontWeight: 600, mt: 0.35 }}
            >
              Идёт дообучение — модалку нельзя закрыть, пока не закончится или не
              сбросишь.
            </Typography>
          ) : null}
        </DialogTitle>
        <Tabs
          value={settingsTab}
          onChange={(_e, v: number) => {
            if (finetuneRunning) return;
            setSettingsTab(v);
          }}
          variant="scrollable"
          scrollButtons="auto"
          sx={{
            px: 1,
            minHeight: 40,
            borderBottom: 1,
            borderColor: "divider",
            "& .MuiTab-root": {
              minHeight: 40,
              textTransform: "none",
              fontWeight: 600,
              fontSize: "0.85rem",
            },
          }}
        >
          <Tab label="Модели" disabled={finetuneRunning} />
          <Tab label="Новости" disabled={finetuneRunning} />
          <Tab label="Дообучение" />
          <Tab label="Данные" disabled={finetuneRunning} />
        </Tabs>
        <DialogContent
          sx={{
            pt: 2,
            flex: 1,
            overflow: "auto",
            minHeight: 280,
          }}
        >
          {settingsTab === 0 && (
            <Box>
              <Typography
                variant="subtitle2"
                color="text.secondary"
                sx={{ mb: 1, fontWeight: 700 }}
              >
                GGUF
              </Typography>
              <FormControl fullWidth size="small" sx={{ mb: 1.25 }}>
                <InputLabel id="chat-gguf-label">Чат</InputLabel>
                <Select
                  labelId="chat-gguf-label"
                  label="Чат"
                  value={chatGguf}
                  onChange={(e) => setChatGguf(String(e.target.value))}
                >
                  {(
                    status?.chat_models?.files ||
                    (status?.chat_models?.profiles || []).map((p) => ({
                      filename: p.filename || p.id,
                      label: p.label,
                      blurb: p.blurb,
                    }))
                  ).map((f) => (
                    <MenuItem key={`chat-${f.filename}`} value={f.filename}>
                      {f.label || f.filename}
                      {f.blurb ? ` — ${f.blurb}` : ""}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" sx={{ mb: 1.25 }}>
                <InputLabel id="code-gguf-label">Кодинг</InputLabel>
                <Select
                  labelId="code-gguf-label"
                  label="Кодинг"
                  value={codeGguf}
                  onChange={(e) => setCodeGguf(String(e.target.value))}
                >
                  {(
                    status?.chat_models?.files ||
                    (status?.chat_models?.profiles || []).map((p) => ({
                      filename: p.filename || p.id,
                      label: p.label,
                      blurb: p.blurb,
                    }))
                  ).map((f) => (
                    <MenuItem key={`code-${f.filename}`} value={f.filename}>
                      {f.label || f.filename}
                      {f.blurb ? ` — ${f.blurb}` : ""}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {chatGguf && codeGguf && chatGguf === codeGguf ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", mb: 1 }}
                >
                  Одна модель на обе роли — второй экземпляр в VRAM не грузится.
                </Typography>
              ) : null}
              {modelsMsg && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
                >
                  {modelsMsg}
                </Typography>
              )}
              <Button
                fullWidth
                variant="contained"
                disabled={busy || modelsBusy || !chatGguf || !codeGguf}
                onClick={() => void applyModels()}
                sx={{ mb: 2 }}
              >
                {modelsBusy ? "Гружу модели…" : "Применить модели"}
              </Button>

              <Typography
                variant="subtitle2"
                color="text.secondary"
                sx={{ mb: 1, fontWeight: 700 }}
              >
                Compute
              </Typography>
              <ToggleButtonGroup
                exclusive
                fullWidth
                size="small"
                value={computeMode}
                onChange={(_e, v) => {
                  if (v) setComputeMode(v);
                }}
                sx={{ mb: 1.25 }}
              >
                <ToggleButton value="cpu">CPU</ToggleButton>
                <ToggleButton value="gpu">GPU</ToggleButton>
                <ToggleButton value="hybrid">Hybrid</ToggleButton>
              </ToggleButtonGroup>
              {computeMode === "hybrid" && (
                <Box sx={{ px: 0.5, mb: 1.25 }}>
                  <Typography variant="caption" color="text.secondary">
                    Слоёв на GPU: {gpuLayers}
                    {status?.compute?.load?.n_layer
                      ? ` / ${status.compute.load.n_layer}`
                      : ""}
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
                <Alert
                  severity={status.compute.llama_gpu_offload ? "success" : "info"}
                  sx={{ mb: 1.25 }}
                >
                  {status.compute.note}
                </Alert>
              )}
              {status?.compute?.load?.n_cpu_layers != null && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", mb: 1 }}
                >
                  Загружено: GPU{" "}
                  {status.compute.load.n_gpu_layers_effective ?? "—"} / CPU{" "}
                  {status.compute.load.n_cpu_layers}
                  {status.compute.load.n_threads
                    ? ` · потоков: ${status.compute.load.n_threads}`
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
                sx={{ mb: 1 }}
              >
                {computeBusy ? "Применяю…" : "Применить compute"}
              </Button>

              <Typography
                variant="subtitle2"
                color="text.secondary"
                sx={{ mt: 2, mb: 1, fontWeight: 700 }}
              >
                Soft-evolve
              </Typography>
              <FormControlLabel
                control={
                  <Switch
                    checked={softDialogue}
                    disabled={busy || softDialogueBusy || finetuneRunning}
                    onChange={(_e, checked) => void applySoftDialogue(checked)}
                  />
                }
                label="Учиться из диалога"
                sx={{ mb: 0.5, ml: 0 }}
              />
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: "block", mb: 1 }}
              >
                Фоном предлагает правки характера/навыков. Без авто-применения:
                подтверди фразой «запомни это» или отклони «не запоминай».
              </Typography>
              {status?.pending_soft ? (
                <Alert severity="info" sx={{ mb: 1 }}>
                  Есть предложение soft-evolve. Approve: «
                  {status.soft_approve_phrase || "запомни это"}».
                </Alert>
              ) : null}
              {softDialogueMsg && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
                >
                  {softDialogueMsg}
                </Typography>
              )}
              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  bgcolor: "transparent",
                  "&:before": { display: "none" },
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="caption" color="text.secondary">
                    Подсказка по Hybrid / GGUF
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  <Typography variant="caption" color="text.secondary" component="div">
                    Hybrid делит слои между GPU и CPU. Меньше слоёв на GPU → больше
                    нагрузка на процессор. Файлы моделей: <code>data/models</code>.
                  </Typography>
                </AccordionDetails>
              </Accordion>
            </Box>
          )}

          {settingsTab === 1 && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
                Выдержек: {newsItems || status?.news?.items || 0}. В чате можно спросить:
                «были упоминания про Озон за неделю?»
              </Typography>
              <FormControl size="small" fullWidth sx={{ mb: 1.25 }}>
                <InputLabel id="news-global-interval-label">
                  Автообновление
                </InputLabel>
                <Select
                  labelId="news-global-interval-label"
                  label="Автообновление"
                  value={newsGlobalInterval}
                  disabled={busy || newsBusy}
                  onChange={(e) => void onGlobalInterval(String(e.target.value))}
                >
                  {newsIntervalOptions.map((opt) => (
                    <MenuItem key={`g-${opt.value}`} value={String(opt.value)}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Stack spacing={1} sx={{ mb: 1.25 }}>
                <Stack direction="row" spacing={1}>
                  <TextField
                    size="small"
                    fullWidth
                    label="RSS URL"
                    placeholder="https://…/rss"
                    value={newsRss}
                    onChange={(e) => setNewsRss(e.target.value)}
                  />
                  <Button
                    variant="outlined"
                    disabled={busy || newsBusy || !newsRss.trim()}
                    onClick={() => void onAddRss()}
                    sx={{ whiteSpace: "nowrap" }}
                  >
                    + RSS
                  </Button>
                </Stack>
                <Stack direction="row" spacing={1}>
                  <TextField
                    size="small"
                    fullWidth
                    label="Telegram"
                    placeholder="@channel"
                    value={newsTg}
                    onChange={(e) => setNewsTg(e.target.value)}
                  />
                  <Button
                    variant="outlined"
                    disabled={busy || newsBusy || !newsTg.trim()}
                    onClick={() => void onAddTg()}
                    sx={{ whiteSpace: "nowrap" }}
                  >
                    + TG
                  </Button>
                </Stack>
              </Stack>
              {(newsRssList.length > 0 || newsTgList.length > 0) && (
                <Box
                  sx={{
                    mb: 1.25,
                    maxHeight: 220,
                    overflow: "auto",
                    border: 1,
                    borderColor: "divider",
                    borderRadius: 1,
                    px: 1,
                    py: 0.5,
                  }}
                >
                  {newsRssList.map((u) => (
                    <Stack
                      key={`rss-${u.url}`}
                      direction="row"
                      spacing={0.75}
                      sx={{ alignItems: "center", mb: 0.5 }}
                    >
                      <Typography
                        variant="caption"
                        sx={{ flex: 1, wordBreak: "break-all", minWidth: 0 }}
                      >
                        RSS: {u.url}
                      </Typography>
                      <FormControl size="small" sx={{ minWidth: 118 }}>
                        <Select
                          value={intervalSelectValue(u.interval ?? "global")}
                          disabled={newsBusy}
                          onChange={(e) =>
                            void onRssInterval(u.url, String(e.target.value))
                          }
                        >
                          {newsSourceIntervalOptions.map((opt) => (
                            <MenuItem
                              key={`rss-iv-${u.url}-${opt.value}`}
                              value={String(opt.value)}
                            >
                              {opt.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Button
                        size="small"
                        color="inherit"
                        disabled={newsBusy}
                        onClick={() => void onRemoveRss(u.url)}
                      >
                        ×
                      </Button>
                    </Stack>
                  ))}
                  {newsTgList.map((c) => (
                    <Stack
                      key={`tg-${c.id}`}
                      direction="row"
                      spacing={0.75}
                      sx={{ alignItems: "center", mb: 0.5 }}
                    >
                      <Typography
                        variant="caption"
                        sx={{ flex: 1, minWidth: 0 }}
                      >
                        TG: @{c.id}
                      </Typography>
                      <FormControl size="small" sx={{ minWidth: 118 }}>
                        <Select
                          value={intervalSelectValue(c.interval ?? "global")}
                          disabled={newsBusy}
                          onChange={(e) =>
                            void onTgInterval(c.id, String(e.target.value))
                          }
                        >
                          {newsSourceIntervalOptions.map((opt) => (
                            <MenuItem
                              key={`tg-iv-${c.id}-${opt.value}`}
                              value={String(opt.value)}
                            >
                              {opt.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Button
                        size="small"
                        color="inherit"
                        disabled={newsBusy}
                        onClick={() => void onRemoveTg(c.id)}
                      >
                        ×
                      </Button>
                    </Stack>
                  ))}
                </Box>
              )}
              {newsMsg && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
                >
                  {newsMsg}
                </Typography>
              )}
              <Button
                fullWidth
                variant="contained"
                disabled={
                  busy ||
                  newsBusy ||
                  (newsRssList.length === 0 && newsTgList.length === 0)
                }
                onClick={() => void onIngestNews()}
                sx={{ mb: 1 }}
              >
                {newsBusy ? "Читаю ленту…" : "Обновить ленту"}
              </Button>
              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  bgcolor: "transparent",
                  "&:before": { display: "none" },
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="caption" color="text.secondary">
                    Как это работает
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  <Typography variant="caption" color="text.secondary" component="div">
                    Источники → обновление ленты → выдержки с ссылкой на первоисточник.
                    Telegram только публичные каналы (<code>t.me/s/…</code>).
                    Автообновление работает, пока запущена Зипка; по умолчанию выкл.
                    Пока идёт ответ в чате — обновление ждёт и стартует после.
                  </Typography>
                </AccordionDetails>
              </Accordion>
            </Box>
          )}

          {settingsTab === 2 && (
            <Box>
              <Stack spacing={0.35} sx={{ mb: 1.25 }}>
                <InfoLine
                  label="Поколение"
                  value={
                    finetuneInfo?.lineage?.generation ??
                    status?.finetune_lineage?.generation ??
                    "—"
                  }
                />
                <InfoLine
                  label="Статус"
                  value={
                    [
                      finetuneInfo?.status?.state || status?.finetune?.state || "idle",
                      finetuneInfo?.status?.phase
                        ? `· ${finetuneInfo.status.phase}`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" ")
                  }
                />
                {finetuneElapsed ? (
                  <InfoLine
                    label="Время"
                    value={
                      finetuneRunning
                        ? finetuneElapsed
                        : `${finetuneElapsed} (стоп)`
                    }
                  />
                ) : null}
                <InfoLine
                  label="GGUF"
                  value={
                    finetuneInfo?.lineage?.active_gguf ||
                    status?.finetune_lineage?.active_gguf ||
                    "—"
                  }
                />
                {finetuneInfo?.pending ? (
                  <InfoLine
                    label="Заявка"
                    value={`gen ${finetuneInfo.pending.generation ?? "?"} · чат ${finetuneInfo.pending.chat_pairs ?? "?"} + id ${finetuneInfo.pending.identity_pairs ?? "?"}`}
                  />
                ) : null}
                {finetuneInfo?.status?.error ? (
                  <Typography variant="caption" color="error" sx={{ display: "block" }}>
                    {String(finetuneInfo.status.error)}
                  </Typography>
                ) : null}
              </Stack>
              {finetuneMsg && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
                >
                  {finetuneMsg}
                </Typography>
              )}
              <Stack spacing={1} sx={{ mb: 1 }}>
                <Button
                  fullWidth
                  variant="outlined"
                  disabled={chatBusy || finetuneBusy}
                  onClick={() => void refreshFinetune().then(() => onRefresh())}
                >
                  Обновить статус
                </Button>
                <Button
                  fullWidth
                  variant="outlined"
                  color="warning"
                  disabled={chatBusy || finetuneBusy}
                  onClick={() => void onAbortFinetune()}
                >
                  Сбросить / прервать
                </Button>
                <Button
                  fullWidth
                  variant="contained"
                  disabled={
                    busy ||
                    finetuneBusy ||
                    finetuneRunning
                  }
                  onClick={() => void onProposeFinetune()}
                >
                  {finetuneBusy ? "Готовлю…" : "Подготовить"}
                </Button>
                <Button
                  fullWidth
                  variant="contained"
                  color="secondary"
                  disabled={
                    busy ||
                    finetuneBusy ||
                    !finetuneInfo?.pending ||
                    finetuneRunning
                  }
                  onClick={() => void onStartFinetune()}
                >
                  {finetuneInfo?.approve_phrase ||
                    status?.finetune_approve_phrase ||
                    "Разрешаю дообучение"}
                </Button>
              </Stack>
              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  bgcolor: "transparent",
                  "&:before": { display: "none" },
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="caption" color="text.secondary">
                    Требования
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  <Typography variant="caption" color="text.secondary" component="div">
                    Чат + persona/skills/preferences → LoRA → новый{" "}
                    <code>zipka-self-gen…gguf</code>. Нужно{" "}
                    <code>pip install -e &quot;.[finetune]&quot;</code>, лучше Qwen2.5/Qwen3.
                    Экспорт GGUF — через llama.cpp.
                  </Typography>
                </AccordionDetails>
              </Accordion>
            </Box>
          )}

          {settingsTab === 3 && (
            <Box>
              <Alert severity="warning" sx={{ mb: 1.5 }}>
                Полный сброс чата, заметок, целей, книг, новостей, патчей и persona.yaml.
                Действие необратимо.
              </Alert>
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
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            onClick={() => {
              if (finetuneRunning) return;
              setSettingsOpen(false);
            }}
            disabled={finetuneRunning}
            sx={{ color: "text.secondary" }}
          >
            {finetuneRunning ? "Закрыть (после обучения)" : "Закрыть"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
