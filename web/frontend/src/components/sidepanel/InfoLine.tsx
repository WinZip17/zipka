import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

export function InfoBlock({ title, children }: { title: string; children: ReactNode }) {
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

type InfoLineVariant = "columns" | "inline";

export function InfoLine({
  label,
  value,
  variant = "columns",
  labelWidth = 132,
}: {
  label: string;
  value: ReactNode;
  variant?: InfoLineVariant;
  labelWidth?: number;
}) {
  if (variant === "inline") {
    return (
      <Typography
        variant="body2"
        sx={{
          py: 0.3,
          lineHeight: 1.45,
          color: "text.primary",
          wordBreak: "break-word",
        }}
      >
        <Box component="span" sx={{ color: "text.secondary", fontWeight: 600 }}>
          {label}:
        </Box>{" "}
        {value}
      </Typography>
    );
  }

  // columns: фиксированный лейбл слева, значение сразу рядом (не у правого края)
  return (
    <Stack
      direction="row"
      spacing={1.25}
      sx={{ alignItems: "flex-start", py: 0.35 }}
    >
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{
          width: labelWidth,
          minWidth: labelWidth,
          flexShrink: 0,
          lineHeight: 1.45,
        }}
      >
        {label}
      </Typography>
      <Typography
        variant="body2"
        sx={{
          flex: 1,
          minWidth: 0,
          color: "text.primary",
          wordBreak: "break-word",
          lineHeight: 1.45,
        }}
      >
        {value}
      </Typography>
    </Stack>
  );
}
