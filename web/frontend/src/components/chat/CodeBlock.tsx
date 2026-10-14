import { useState } from "react";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { langLabel } from "../../chat/parseFencedCode";

type Props = {
  lang: string;
  code: string;
};

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fallback below */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function CodeBlock({ lang, code }: Props) {
  const [copied, setCopied] = useState(false);
  const label = langLabel(lang);

  const onCopy = async () => {
    const ok = await copyText(code);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Box
      sx={{
        my: 1,
        borderRadius: 1,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        bgcolor: "rgba(0,0,0,0.35)",
        maxWidth: "100%",
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1,
          px: 1.25,
          py: 0.5,
          bgcolor: "rgba(0,0,0,0.28)",
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Typography
          variant="caption"
          sx={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
            color: "text.secondary",
            fontWeight: 700,
            letterSpacing: "0.04em",
            textTransform: "lowercase",
          }}
        >
          {label}
        </Typography>
        <Tooltip title={copied ? "Скопировано" : "Скопировать"}>
          <IconButton
            size="small"
            onClick={() => void onCopy()}
            aria-label="Скопировать код"
            sx={{
              color: copied ? "primary.main" : "text.secondary",
              borderRadius: 1,
              px: 0.75,
              py: 0.25,
              gap: 0.5,
              "&:hover": { bgcolor: "rgba(255,255,255,0.06)" },
            }}
          >
            {copied ? (
              <CheckIcon sx={{ fontSize: 15 }} />
            ) : (
              <ContentCopyIcon sx={{ fontSize: 15 }} />
            )}
            <Typography
              component="span"
              variant="caption"
              sx={{ fontWeight: 600, lineHeight: 1, display: { xs: "none", sm: "inline" } }}
            >
              {copied ? "Скопировано" : "Скопировать"}
            </Typography>
          </IconButton>
        </Tooltip>
      </Box>
      <Box
        component="pre"
        sx={{
          m: 0,
          px: 1.5,
          py: 1.25,
          overflowX: "auto",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          fontSize: "0.8rem",
          lineHeight: 1.5,
          color: "text.primary",
          whiteSpace: "pre",
        }}
      >
        <code>{code}</code>
      </Box>
    </Box>
  );
}
