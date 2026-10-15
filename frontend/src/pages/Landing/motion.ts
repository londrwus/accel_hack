/** Shared motion values for the landing page (docs/DESIGN.md → Motion). */
export const EASE = [0.22, 1, 0.36, 1] as const;

/** Per-letter headline rise: 15ms stagger, 600ms per letter. */
export const LETTER_STAGGER = 0.015;
export const LETTER_DURATION = 0.6;

/** When the fade-ups after the headline start (seconds). */
export const FADE_START = 0.45;
export const FADE_STEP = 0.09;

/** Fade-up (y 12 → 0, opacity 0 → 1). */
export function fadeUp(delay: number) {
  return {
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.7, ease: EASE, delay },
  };
}
