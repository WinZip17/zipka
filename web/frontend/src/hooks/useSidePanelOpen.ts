import { useCallback, useEffect, useState } from "react";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

const STORAGE_KEY = "zipka.sidePanelOpen";
const MD_MIN = 900;

function readStored(): boolean | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "1") return true;
    if (raw === "0") return false;
  } catch {
    /* ignore */
  }
  return null;
}

function writeStored(open: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, open ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function defaultOpenForViewport(): boolean {
  if (typeof window === "undefined") return true;
  return window.innerWidth >= MD_MIN;
}

/** Состояние боковой панели: десктоп по умолчанию открыта, мобилка — закрыта. */
export function useSidePanelOpen() {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"), {
    noSsr: true,
  });
  const [open, setOpenState] = useState(() => {
    const stored = readStored();
    if (stored !== null) return stored;
    return defaultOpenForViewport();
  });

  // Первый заход без localStorage: подстроить под breakpoint при смене ширины
  useEffect(() => {
    if (readStored() !== null) return;
    setOpenState(isDesktop);
  }, [isDesktop]);

  const setOpen = useCallback((value: boolean | ((prev: boolean) => boolean)) => {
    setOpenState((prev) => {
      const next = typeof value === "function" ? value(prev) : value;
      writeStored(next);
      return next;
    });
  }, []);

  const toggle = useCallback(() => {
    setOpen((prev) => !prev);
  }, [setOpen]);

  return { open, setOpen, toggle, isDesktop };
}
