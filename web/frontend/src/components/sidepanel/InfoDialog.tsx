import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";
import type { StatusResponse } from "../../api";
import { dialogPaperSx } from "./styles";
import { InfoBlock, InfoLine } from "./InfoLine";

type Props = {
  open: boolean;
  onClose: () => void;
  status: StatusResponse | null;
  sensorsFeature: boolean;
  eyesOn: boolean;
  earsOn: boolean;
};

export function InfoDialog({
  open,
  onClose,
  status,
  sensorsFeature,
  eyesOn,
  earsOn,
}: Props) {
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
    <Dialog
      open={open}
      onClose={onClose}
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
            variant="inline"
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
            variant="inline"
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
            variant="inline"
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
            <InfoLine label="Файл чата" value={status.llm.model_path} variant="inline" />
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
            <InfoLine
              label="Vision"
              variant="inline"
              value={status?.vision_model || status?.model || "—"}
            />
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
          <InfoLine
            label="В настройках"
            variant="inline"
            value={sensorsFeature ? "разрешены" : "выкл"}
          />
          {sensorsFeature ? (
            <>
              <InfoLine label="Глаза" value={eyesOn ? "вкл" : "выкл"} variant="inline" />
              <InfoLine label="Уши" value={earsOn ? "вкл" : "выкл"} variant="inline" />
            </>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Блок на главной скрыт. Включи «Сенсоры» в Настройках → Модели.
            </Typography>
          )}
        </InfoBlock>

        <InfoBlock title="Патчи кода">
          <InfoLine label="Ожидает" value={status?.pending_patch ? "да" : "нет"} variant="inline" />
          <InfoLine label="Фраза approve" value={`«${approvePhrase}»`} variant="inline" />
        </InfoBlock>

        <InfoBlock title="Проактивность">
          <InfoLine
            label="Пинги сегодня"
            variant="inline"
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
        <Button onClick={onClose} sx={{ color: "text.secondary" }}>
          Закрыть
        </Button>
      </DialogActions>
    </Dialog>
  );
}
