import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("lets later Tailwind classes win", () => {
    expect(cn("px-2 text-ink", false, "px-4")).toBe("text-ink px-4");
  });
});
