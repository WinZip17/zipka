import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Slider from "@mui/material/Slider";
import Switch from "@mui/material/Switch";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import type { StatusResponse } from "../../api";

type Props = {
  status: StatusResponse | null;
  busy: boolean;
  finetuneRunning: boolean;
  chatGguf: string;
  codeGguf: string;
  onChatGguf: (v: string) => void;
  onCodeGguf: (v: string) => void;
  modelsBusy: boolean;
  modelsMsg: string | null;
  onApplyModels: () => void;
  computeMode: "cpu" | "gpu" | "hybrid";
  onComputeMode: (v: "cpu" | "gpu" | "hybrid") => void;
  gpuLayers: number;
  onGpuLayers: (v: number) => void;
  computeBusy: boolean;
  computeMsg: string | null;
  onApplyCompute: () => void;
  softDialogue: boolean;
  softDialogueBusy: boolean;
  softDialogueMsg: string | null;
  onApplySoftDialogue: (enabled: boolean) => void;
  sensorsFeature: boolean;
  sensorsFeatureBusy: boolean;
  sensorsFeatureMsg: string | null;
  onApplySensorsFeature: (enabled: boolean) => void;
  notifyVolumePct: number;
  onNotifyVolumePct: (pct: number) => void;
  notifySoundMsg: string | null;
  onPreviewSound: () => void;
};

export function ModelsTab({
  status,
  busy,
  finetuneRunning,
  chatGguf,
  codeGguf,
  onChatGguf,
  onCodeGguf,
  modelsBusy,
  modelsMsg,
  onApplyModels,
  computeMode,
  onComputeMode,
  gpuLayers,
  onGpuLayers,
  computeBusy,
  computeMsg,
  onApplyCompute,
  softDialogue,
  softDialogueBusy,
  softDialogueMsg,
  onApplySoftDialogue,
  sensorsFeature,
  sensorsFeatureBusy,
  sensorsFeatureMsg,
  onApplySensorsFeature,
  notifyVolumePct,
  onNotifyVolumePct,
  notifySoundMsg,
  onPreviewSound,
}: Props) {
  return (
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
          onChange={(e) => onChatGguf(String(e.target.value))}
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
          onChange={(e) => onCodeGguf(String(e.target.value))}
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
        onClick={() => void onApplyModels()}
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
          if (v) onComputeMode(v);
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
            onChange={(_e, v) => onGpuLayers(Array.isArray(v) ? v[0] : v)}
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
        onClick={() => void onApplyCompute()}
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
            onChange={(_e, checked) => void onApplySoftDialogue(checked)}
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

      <Typography
        variant="subtitle2"
        color="text.secondary"
        sx={{ mt: 2, mb: 1, fontWeight: 700 }}
      >
        Сенсоры
      </Typography>
      <FormControlLabel
        control={
          <Switch
            checked={sensorsFeature}
            disabled={busy || sensorsFeatureBusy || finetuneRunning}
            onChange={(_e, checked) => void onApplySensorsFeature(checked)}
          />
        }
        label="Разрешить сенсоры"
        sx={{ mb: 0.5, ml: 0 }}
      />
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", mb: 1 }}
      >
        Master-switch для глаз и ушей. Выкл — блока «Сенсоры» на главной
        нет, камера/микрофон погашены. Вкл — блок появляется, сенсоры по
        умолчанию выключены (включаются кнопками или фразой).
      </Typography>
      {sensorsFeatureMsg && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
        >
          {sensorsFeatureMsg}
        </Typography>
      )}

      <Typography
        variant="subtitle2"
        color="text.secondary"
        sx={{ mt: 2, mb: 1, fontWeight: 700 }}
      >
        Звук ответа
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", mb: 1 }}
      >
        Сигнал, когда Зипка ответила в чате (долгие ответы). Громкость 0 —
        без звука.
      </Typography>
      <Typography variant="caption" color="text.secondary">
        Громкость: {notifyVolumePct}%
        {notifyVolumePct === 0 ? " (выкл)" : ""}
      </Typography>
      <Slider
        size="small"
        min={0}
        max={100}
        step={5}
        value={notifyVolumePct}
        valueLabelDisplay="auto"
        valueLabelFormat={(v) => `${v}%`}
        onChange={(_e, v) => {
          const pct = Array.isArray(v) ? v[0] : v;
          onNotifyVolumePct(pct);
        }}
        sx={{ mb: 1, mt: 0.5 }}
      />
      <Button
        size="small"
        variant="outlined"
        disabled={notifyVolumePct === 0}
        onClick={onPreviewSound}
        sx={{ mb: 1 }}
      >
        Прослушать
      </Button>
      {notifySoundMsg && (
        <Typography
          variant="caption"
          color="error"
          sx={{ display: "block", whiteSpace: "pre-wrap", mb: 1 }}
        >
          {notifySoundMsg}
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
  );
}
