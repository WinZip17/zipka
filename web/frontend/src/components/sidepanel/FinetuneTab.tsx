import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { FinetuneStatusResponse, StatusResponse } from "../../types";
import { InfoLine } from "./InfoLine";

type Props = {
  status: StatusResponse | null;
  busy: boolean;
  chatBusy: boolean;
  finetuneBusy: boolean;
  finetuneRunning: boolean;
  finetuneMsg: string | null;
  finetuneInfo: FinetuneStatusResponse | null;
  finetuneElapsed: string | null;
  onRefreshFinetune: () => void;
  onAbortFinetune: () => void;
  onResetFinetune: () => void;
  onProposeFinetune: () => void;
  onStartFinetune: () => void;
};

export function FinetuneTab({
  status,
  busy,
  chatBusy,
  finetuneBusy,
  finetuneRunning,
  finetuneMsg,
  finetuneInfo,
  finetuneElapsed,
  onRefreshFinetune,
  onAbortFinetune,
  onResetFinetune,
  onProposeFinetune,
  onStartFinetune,
}: Props) {
  return (
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
          onClick={() => void onRefreshFinetune()}
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
          variant="outlined"
          color="error"
          disabled={chatBusy || finetuneBusy || finetuneRunning}
          onClick={() => void onResetFinetune()}
          sx={{ borderColor: "#8a3a3a", color: "#e8b4b4" }}
        >
          Сбросить дообучение (с нуля)
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
            Экспорт GGUF — через llama.cpp. «Сбросить дообучение (с нуля)»
            удаляет self-GGUF и артефакты, возвращает базовую модель из
            lineage; чат/память не трогает. Фраза: «подтверждаю сброс
            дообучения».
          </Typography>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}
