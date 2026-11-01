/**
 * Series colours follow the entity (WEB-DASHBOARD.md §4.5, BRAND.md §5.5): slots in order of
 * first appearance in the page's primary list, kept when a filter removes a series, past 8
 * folded into "Other". Colours are CSS variables, so they follow the theme.
 */
export const SLOTS = 8;
export const seriesColor = (slot: number): string => `var(--series-${(slot % SLOTS) + 1})`;

/** Slot per key, by first appearance; keys past the 8th get none. */
export function assignSlots(keys: Iterable<string>): Map<string, number> {
  const slots = new Map<string, number>();
  for (const key of keys) {
    if (!slots.has(key) && slots.size < SLOTS) slots.set(key, slots.size);
  }
  return slots;
}

export function colorOf(slots: Map<string, number>, key: string): string | undefined {
  const slot = slots.get(key);
  return slot === undefined ? undefined : seriesColor(slot);
}
