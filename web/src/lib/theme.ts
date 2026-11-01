import { useSyncExternalStore } from "react";

/** Light or dark, as public/theme.js set it before the first paint; the reader's choice is
 * kept in localStorage, otherwise the system's applies. */
export type Theme = "light" | "dark";
const KEY = "undercurrent.theme";
const listeners = new Set<() => void>();

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // private mode: the choice lasts for this page
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const media = matchMedia("(prefers-color-scheme: dark)");
  const follow = () => {
    let chosen: string | null = null;
    try {
      chosen = localStorage.getItem(KEY);
    } catch {
      chosen = null;
    }
    if (chosen === null) {
      document.documentElement.dataset.theme = media.matches ? "dark" : "light";
      listener();
    }
  };
  media.addEventListener("change", follow);
  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", follow);
  };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}
