import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { earsAction } from "../api";
import { playReplySound } from "../notifySound";

export type EarPhase = "idle" | "recording" | "transcribing" | "replying";

type Opts = {
  earsOn: boolean;
  busy: boolean;
  onBubble: (text: string, who: "user" | "bot") => void;
  onBusy: (busy: boolean) => void;
  onThinking: (hint: string | null) => void;
  onRefresh: () => void;
};

export function useEarHold({
  earsOn,
  busy,
  onBubble,
  onBusy,
  onThinking,
  onRefresh,
}: Opts) {
  const [earPhase, setEarPhase] = useState<EarPhase>("idle");
  const earSessionRef = useRef(false);
  const earServerStartedRef = useRef(false);
  const earBusyRef = useRef(false);

  const stopEarSession = async () => {
    if (earBusyRef.current) return;
    earBusyRef.current = true;
    setEarPhase("transcribing");
    onBusy(true);
    onThinking("Распознаю речь…");
    try {
      const data = await earsAction("listen_stop");
      if (data.heard) onBubble(`(уши) ${data.heard}`, "user");
      if (data.skipped_chat) {
        if (data.heard === "(слишком коротко)") {
          onBubble(
            "Слишком коротко — зажми микрофон и говори дольше.",
            "bot",
          );
        }
        return;
      }
      setEarPhase("replying");
      onThinking("Вникаю…");
      if (data.comment) onBubble(data.comment, "bot");
      if (data.reply) {
        onBubble(data.reply, "bot");
        playReplySound();
      } else if (data.detail) onBubble(String(data.detail), "bot");
      else if (data.message) onBubble(data.message, "bot");
      onRefresh();
    } catch (err) {
      onBubble(err instanceof Error ? err.message : String(err), "bot");
    } finally {
      earBusyRef.current = false;
      earServerStartedRef.current = false;
      setEarPhase("idle");
      onThinking(null);
      onBusy(false);
    }
  };

  const startEarHold = async (e: ReactPointerEvent<HTMLButtonElement>) => {
    e.preventDefault();
    if (busy || !earsOn || earSessionRef.current || earBusyRef.current) return;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    earSessionRef.current = true;
    earServerStartedRef.current = false;
    setEarPhase("recording");
    onThinking("● Запись… говори");
    try {
      await earsAction("listen_start");
      earServerStartedRef.current = true;
    } catch (err) {
      earSessionRef.current = false;
      earServerStartedRef.current = false;
      setEarPhase("idle");
      onThinking(null);
      onBubble(err instanceof Error ? err.message : String(err), "bot");
      return;
    }
    if (!earSessionRef.current) {
      await stopEarSession();
    }
  };

  const endEarHold = () => {
    if (!earSessionRef.current) return;
    earSessionRef.current = false;
    if (earServerStartedRef.current) {
      void stopEarSession();
    }
  };

  return {
    earPhase,
    startEarHold,
    endEarHold,
  };
}
