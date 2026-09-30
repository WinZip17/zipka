import type { ReactNode } from "react";
import Typography from "@mui/material/Typography";

export function SectionTitle({ children }: { children: ReactNode }) {
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

export function intervalSelectValue(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "off";
  return String(raw);
}

export function parseIntervalChoice(value: string): string | number {
  if (value === "off" || value === "global") return value;
  const n = Number(value);
  return Number.isFinite(n) ? n : "global";
}

export function formatElapsedHms(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

export function parseUtcMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}
