import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import type {
  NewsIntervalOption,
  NewsRssSource,
  NewsTelegramSource,
  StatusResponse,
} from "../../types";
import { intervalSelectValue } from "./utils";

type Props = {
  status: StatusResponse | null;
  busy: boolean;
  newsBusy: boolean;
  newsMsg: string | null;
  newsItems: number;
  newsRss: string;
  newsTg: string;
  onNewsRss: (v: string) => void;
  onNewsTg: (v: string) => void;
  newsRssList: NewsRssSource[];
  newsTgList: NewsTelegramSource[];
  newsGlobalInterval: string;
  newsIntervalOptions: NewsIntervalOption[];
  newsSourceIntervalOptions: NewsIntervalOption[];
  onAddRss: () => void;
  onAddTg: () => void;
  onRemoveRss: (url: string) => void;
  onRemoveTg: (ch: string) => void;
  onGlobalInterval: (value: string) => void;
  onRssInterval: (url: string, value: string) => void;
  onTgInterval: (ch: string, value: string) => void;
  onIngestNews: () => void;
};

export function NewsTab({
  status,
  busy,
  newsBusy,
  newsMsg,
  newsItems,
  newsRss,
  newsTg,
  onNewsRss,
  onNewsTg,
  newsRssList,
  newsTgList,
  newsGlobalInterval,
  newsIntervalOptions,
  newsSourceIntervalOptions,
  onAddRss,
  onAddTg,
  onRemoveRss,
  onRemoveTg,
  onGlobalInterval,
  onRssInterval,
  onTgInterval,
  onIngestNews,
}: Props) {
  return (
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
            onChange={(e) => onNewsRss(e.target.value)}
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
            onChange={(e) => onNewsTg(e.target.value)}
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
  );
}
