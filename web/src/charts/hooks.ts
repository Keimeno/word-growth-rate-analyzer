import { useMemo, useSyncExternalStore } from "react";
import { useTheme } from "@/lib/theme";
import { type ChartTokens, chartTokens } from "./theme";

const motion = matchMedia("(prefers-reduced-motion: reduce)");
const subscribeMotion = (listener: () => void) => {
  motion.addEventListener("change", listener);
  return () => motion.removeEventListener("change", listener);
};

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, () => motion.matches);
}

/** The chart tokens of the current theme, read from the page's CSS. */
export function useChartTokens(): ChartTokens {
  const theme = useTheme();
  // the CSS variables change with the theme's data attribute, set before `theme` updates
  return useMemo(() => (theme === "dark" ? chartTokens() : chartTokens()), [theme]);
}
