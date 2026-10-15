import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "motion/react";
import { EASE } from "./motion";

const fmt = new Intl.NumberFormat("en-GB");

/** A number that counts up from 0 (formatted "3,000"). Shows the final value straight away with reduced motion. */
export function CountUp({ value, delay = 0, duration = 1.4 }: { value: number; delay?: number; duration?: number }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setShown(value);
      return;
    }
    const controls = animate(0, value, {
      duration,
      delay,
      ease: EASE,
      onUpdate: (v) => setShown(Math.round(v)),
    });
    return () => controls.stop();
  }, [value, delay, duration, reduce]);

  return <>{fmt.format(shown)}</>;
}
