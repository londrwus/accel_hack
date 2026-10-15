import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { EASE, LETTER_DURATION, LETTER_STAGGER } from "./motion";

const LINES = ["The first systematic", "VC operating system."];
// Pencil renders the 96px headline with an fi ligature that Chrome drops under negative letter-spacing;
// -1.48px (design: -1.2px) brings both lines back to the design width.
const TEXT_CLASS = "m-0 text-[96px]/[96px] font-normal tracking-[-1.48px] text-ink whitespace-nowrap max-md:text-[44px]/[48px] max-md:tracking-[-0.6px]";

/**
 * Hero h1 with Lightfern's per-letter rise: each character sits in an overflow-clipped span and slides up
 * from 100%. Once the last letter lands, the split spans are swapped for plain text so kerning matches the design.
 */
export function Headline() {
  const reduce = useReducedMotion();
  const [settled, setSettled] = useState(false);

  if (reduce || settled) {
    return (
      <h1 className={TEXT_CLASS}>
        {LINES[0]}
        <br />
        {LINES[1]}
      </h1>
    );
  }

  const total = LINES.join("").replace(/ /g, "").length;
  let index = 0;

  return (
    <h1 className={TEXT_CLASS} aria-label={LINES.join(" ")}>
      {LINES.map((line, li) => (
        <span key={li} aria-hidden className="block">
          {line.split(" ").map((word, wi, words) => (
            <span key={wi}>
              <span className="inline-block whitespace-nowrap">
                {[...word].map((ch, ci) => {
                  const i = index++;
                  const last = i === total - 1;
                  return (
                    // Padding + matching negative margin so descenders (y, g, p) aren't clipped.
                    <span key={ci} className="-my-[0.18em] inline-block overflow-hidden py-[0.18em] align-top">
                      <motion.span
                        className="inline-block"
                        initial={{ y: "120%" }}
                        animate={{ y: "0%" }}
                        transition={{ duration: LETTER_DURATION, ease: EASE, delay: 0.05 + i * LETTER_STAGGER }}
                        onAnimationComplete={last ? () => setSettled(true) : undefined}
                      >
                        {ch}
                      </motion.span>
                    </span>
                  );
                })}
              </span>
              {wi < words.length - 1 ? " " : null}
            </span>
          ))}
        </span>
      ))}
    </h1>
  );
}
