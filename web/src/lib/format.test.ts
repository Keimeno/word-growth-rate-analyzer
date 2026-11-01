import { describe, expect, it } from "vitest";
import {
  confidence,
  count,
  duration,
  perThousand,
  percent,
  signedPercent,
  strength,
  times,
} from "./format";

describe("numbers as the brand words them", () => {
  it("counts in full below 10,000, compact above", () => {
    expect(count(1284)).toBe("1,284");
    expect(count(12_840)).toBe("12.8K");
    expect(count(null)).toBe("–");
  });
  it("gives small shares the digits they need", () => {
    expect(perThousand(12.345)).toBe("12.3");
    expect(perThousand(0.0123)).toBe("0.012");
    expect(perThousand(0)).toBe("0");
  });
  it("says times usual, or new", () => {
    expect(times(12.4)).toBe("×12");
    expect(times(2.44)).toBe("×2.4");
    expect(times(3, true)).toBe("new");
  });
  it("signs changes with a real minus", () => {
    expect(signedPercent(-4.2)).toBe("−4.2%");
    expect(signedPercent(21)).toBe("+21%");
    expect(percent(0.583)).toBe("58%");
  });
  it("words hours", () => {
    expect(duration(0.4)).toBe("24 min");
    expect(duration(18)).toBe("18 h");
    expect(duration(60)).toBe("2.5 d");
  });
  it("turns statistics into words", () => {
    expect(strength(9.4).label).toBe("strong");
    expect(strength(12).level).toBe(3);
    expect(confidence(0.0004).label).toBe("very strong");
    expect(confidence(0.03).label).toBe("moderate");
  });
});
