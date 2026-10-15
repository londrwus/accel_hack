import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "motion/react";
import { EASE } from "./motion";

/** A number that counts up from 0. `decimals` keeps e.g. "3.2". Shows the final value straight away with reduced motion. */
export function CountUp({ value, decimals = 0, delay = 0, duration = 1.2 }: { value: number; decimals?: number; delay?: number; duration?: number }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setShown(value);
      return;
    }
    const controls = animate(0, value, { duration, delay, ease: EASE, onUpdate: setShown });
    return () => controls.stop();
  }, [value, delay, duration, reduce]);

  return <>{shown.toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</>;
}
