/** Звук появления ответа Зипки в чате (localStorage). */

const STORAGE_KEY = "zipka.notify_volume";
/** 0…1, дефолт умеренный */
const DEFAULT_VOLUME = 0.45;
const SOUND_URL = "/sounds/oh-oh-icq.mp3";

let audioEl: HTMLAudioElement | null = null;

export function getNotifyVolume(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null || raw === "") return DEFAULT_VOLUME;
    const n = Number(raw);
    if (!Number.isFinite(n)) return DEFAULT_VOLUME;
    return Math.min(1, Math.max(0, n));
  } catch {
    return DEFAULT_VOLUME;
  }
}

/** Громкость 0…1; 0 = без звука. */
export function setNotifyVolume(volume: number): number {
  const v = Math.min(1, Math.max(0, Number(volume) || 0));
  try {
    localStorage.setItem(STORAGE_KEY, String(v));
  } catch {
    /* ignore quota / private mode */
  }
  if (audioEl) audioEl.volume = v;
  return v;
}

function ensureAudio(): HTMLAudioElement | null {
  if (typeof Audio === "undefined") return null;
  if (!audioEl) {
    audioEl = new Audio(SOUND_URL);
    audioEl.preload = "auto";
  }
  return audioEl;
}

/** Разблокировать автоплей после жеста пользователя (отправка сообщения). */
export function unlockReplySound(): void {
  const el = ensureAudio();
  if (!el) return;
  const vol = getNotifyVolume();
  if (vol <= 0) return;
  try {
    el.volume = 0.001;
    const p = el.play();
    if (p && typeof p.then === "function") {
      void p
        .then(() => {
          el.pause();
          el.currentTime = 0;
          el.volume = vol;
        })
        .catch(() => {
          /* ещё рано для autoplay — попробуем при ответе */
        });
    }
  } catch {
    /* ignore */
  }
}

/** Сыграть звук ответа; при громкости 0 — ничего. */
export function playReplySound(): void {
  const vol = getNotifyVolume();
  if (vol <= 0) return;
  const el = ensureAudio();
  if (!el) return;
  try {
    el.volume = vol;
    el.currentTime = 0;
    void el.play().catch(() => {
      /* autoplay blocked */
    });
  } catch {
    /* ignore */
  }
}
