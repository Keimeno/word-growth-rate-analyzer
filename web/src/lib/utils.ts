import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Class names, later ones winning over Tailwind classes they conflict with. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
