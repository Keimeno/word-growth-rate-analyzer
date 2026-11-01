import { describe, expect, it } from "vitest";
import { assignSlots, colorOf } from "./colors";

describe("colour follows the entity", () => {
  it("assigns slots by first appearance and stops at 8", () => {
    const slots = assignSlots(["b", "a", "b", "c", "d", "e", "f", "g", "h", "i"]);
    expect(slots.get("b")).toBe(0);
    expect(slots.get("a")).toBe(1);
    expect(slots.get("i")).toBeUndefined();
    expect(colorOf(slots, "a")).toBe("var(--series-2)");
  });
});
