import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import {
  abortFinetune,
  addNewsSource,
  fetchFinetuneStatus,
  fetchNewsSources,
  finetuneResetInfo,
  ingestNews,
  proposeFinetune,
  resetFinetune,
  resetInfo,
  resetLearning,
  saveNewsSources,
  setCompute,
  setModels,
  setNewsSchedule,
  setSoftEvolveDialogue,
  setSensorsEnabled,
  startFinetune,
} from "../../api";
import {
  getNotifyVolume,
  playReplySound,
  setNotifyVolume,
} from "../../notifySound";
import type {
  FinetuneStatusResponse,
  NewsIntervalOption,
  NewsRssSource,
  NewsTelegramSource,
  StatusResponse,
} from "../../types";
import { DataTab } from "./DataTab";
import { FinetuneTab } from "./FinetuneTab";
import { ModelsTab } from "./ModelsTab";
import { NewsTab } from "./NewsTab";
import { dialogPaperSx } from "./styles";
import {
  formatElapsedHms,
  intervalSelectValue,
  parseIntervalChoice,
  parseUtcMs,
} from "./utils";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  settingsTab: number;
  onSettingsTabChange: (tab: number) => void;
  status: StatusResponse | null;
  chatBusy: boolean;
  sensorsFeature: boolean;
  onSensorsFeatureChange: (enabled: boolean) => void;
  onBubble: (text: string, who: "user" | "bot") => void;
  onThinking: (hint: string | null) => void;
  onRefresh: () => void;
  onResetChat: () => void;
};

export function SettingsDialog({
  open,
  onOpenChange,
  settingsTab,
  onSettingsTabChange,
  status,
  chatBusy,
  sensorsFeature,
  onSensorsFeatureChange,
  onBubble,
  onThinking,
  onRefresh,
  onResetChat,
}: Props) {
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
  const [sensorsFeatureBusy, setSensorsFeatureBusy] = useState(false);
  const [sensorsFeatureMsg, setSensorsFeatureMsg] = useState<string | null>(
    null,
  );
  const [notifyVolumePct, setNotifyVolumePct] = useState(() =>
    Math.round(getNotifyVolume() * 100),
  );
  const [notifySoundMsg, setNotifySoundMsg] = useState<string | null>(null);
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
    if (!open) return;
    void refreshFinetune();
    void refreshNews();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const state = finetuneInfo?.status?.state;
    if (state !== "running" && state !== "succeeded_pending_apply") return;
    const id = window.setInterval(() => {
      void refreshFinetune().then(() => onRefresh());
    }, 5000);
    return () => window.clearInterval(id);
  }, [open, finetuneInfo?.status?.state, onRefresh]);

  useEffect(() => {
    if (!finetuneRunning || finetuneStartedMs == null) return;
    setFinetuneNowMs(Date.now());
    const id = window.setInterval(() => setFinetuneNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [finetuneRunning, finetuneStartedMs]);

  useEffect(() => {
    if (!finetuneRunning) return;
    onOpenChange(true);
    onSettingsTabChange(2);
  }, [finetuneRunning, onOpenChange, onSettingsTabChange]);

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
      onSettingsTabChange(2);
      onOpenChange(true);
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

  const onResetFinetune = async () => {
    if (finetuneRunning) return;
    const info = await finetuneResetInfo();
    const phrase =
      info.confirm_phrase ||
      status?.finetune_reset_phrase ||
      "подтверждаю сброс дообучения";
    const base = info.base_gguf || "базовую GGUF";
    const ok = window.confirm(
      "Сбросить дообучение и начать заново?\n\n" +
        "Удалятся: zipka-self*.gguf, adapters/checkpoints/datasets/jobs, " +
        "pending/status/lineage history.\n" +
        `Чат вернётся на: ${base}\n` +
        "Чат, persona, память и кэш HuggingFace НЕ трогаем.\n\n" +
        "Это необратимо для артефактов дообучения.",
    );
    if (!ok) {
      setFinetuneMsg("Сброс дообучения отменён.");
      return;
    }
    const typed = window.prompt(`Для подтверждения введи фразу:\n${phrase}`, "");
    if (typed === null) {
      setFinetuneMsg("Сброс дообучения отменён.");
      return;
    }
    setFinetuneBusy(true);
    setFinetuneMsg(null);
    try {
      const data = await resetFinetune(typed);
      await refreshFinetune();
      setFinetuneMsg(data.message || "Дообучение сброшено.");
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

  const applySensorsFeature = async (enabled: boolean) => {
    setSensorsFeatureBusy(true);
    setSensorsFeatureMsg(null);
    onSensorsFeatureChange(enabled);
    try {
      const data = await setSensorsEnabled(enabled);
      onSensorsFeatureChange(Boolean(data.sensors_enabled));
      setSensorsFeatureMsg(
        data.sensors_enabled
          ? "Сенсоры разрешены: блок появится на главной, глаза/уши по умолчанию выкл."
          : "Сенсоры выключены: блок скрыт, глаза и уши погашены.",
      );
      onRefresh();
    } catch (err) {
      onSensorsFeatureChange(!enabled);
      setSensorsFeatureMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorsFeatureBusy(false);
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
      onOpenChange(false);
      onResetChat();
      onBubble(data.message || "Обучение сброшено.", "bot");
      onRefresh();
    } catch (err) {
      onBubble(err instanceof Error ? err.message : "Сброс не выполнен", "bot");
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (finetuneRunning) return;
        onOpenChange(false);
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
          onSettingsTabChange(v);
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
          <ModelsTab
            status={status}
            busy={busy}
            finetuneRunning={finetuneRunning}
            chatGguf={chatGguf}
            codeGguf={codeGguf}
            onChatGguf={setChatGguf}
            onCodeGguf={setCodeGguf}
            modelsBusy={modelsBusy}
            modelsMsg={modelsMsg}
            onApplyModels={applyModels}
            computeMode={computeMode}
            onComputeMode={setComputeMode}
            gpuLayers={gpuLayers}
            onGpuLayers={setGpuLayers}
            computeBusy={computeBusy}
            computeMsg={computeMsg}
            onApplyCompute={applyCompute}
            softDialogue={softDialogue}
            softDialogueBusy={softDialogueBusy}
            softDialogueMsg={softDialogueMsg}
            onApplySoftDialogue={applySoftDialogue}
            sensorsFeature={sensorsFeature}
            sensorsFeatureBusy={sensorsFeatureBusy}
            sensorsFeatureMsg={sensorsFeatureMsg}
            onApplySensorsFeature={applySensorsFeature}
            notifyVolumePct={notifyVolumePct}
            onNotifyVolumePct={(pct) => {
              setNotifyVolumePct(pct);
              setNotifyVolume(pct / 100);
            }}
            notifySoundMsg={notifySoundMsg}
            onPreviewSound={() => {
              setNotifySoundMsg(null);
              void playReplySound().then((err) => {
                if (err) setNotifySoundMsg(err);
              });
            }}
          />
        )}

        {settingsTab === 1 && (
          <NewsTab
            status={status}
            busy={busy}
            newsBusy={newsBusy}
            newsMsg={newsMsg}
            newsItems={newsItems}
            newsRss={newsRss}
            newsTg={newsTg}
            onNewsRss={setNewsRss}
            onNewsTg={setNewsTg}
            newsRssList={newsRssList}
            newsTgList={newsTgList}
            newsGlobalInterval={newsGlobalInterval}
            newsIntervalOptions={newsIntervalOptions}
            newsSourceIntervalOptions={newsSourceIntervalOptions}
            onAddRss={onAddRss}
            onAddTg={onAddTg}
            onRemoveRss={onRemoveRss}
            onRemoveTg={onRemoveTg}
            onGlobalInterval={onGlobalInterval}
            onRssInterval={onRssInterval}
            onTgInterval={onTgInterval}
            onIngestNews={onIngestNews}
          />
        )}

        {settingsTab === 2 && (
          <FinetuneTab
            status={status}
            busy={busy}
            chatBusy={chatBusy}
            finetuneBusy={finetuneBusy}
            finetuneRunning={finetuneRunning}
            finetuneMsg={finetuneMsg}
            finetuneInfo={finetuneInfo}
            finetuneElapsed={finetuneElapsed}
            onRefreshFinetune={() => {
              void refreshFinetune().then(() => onRefresh());
            }}
            onAbortFinetune={onAbortFinetune}
            onResetFinetune={onResetFinetune}
            onProposeFinetune={onProposeFinetune}
            onStartFinetune={onStartFinetune}
          />
        )}

        {settingsTab === 3 && (
          <DataTab busy={busy} onReset={onReset} />
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button
          onClick={() => {
            if (finetuneRunning) return;
            onOpenChange(false);
          }}
          disabled={finetuneRunning}
          sx={{ color: "text.secondary" }}
        >
          {finetuneRunning ? "Закрыть (после обучения)" : "Закрыть"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
