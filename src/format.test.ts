// The elapsed-time label of the Quick Install progress row.
import { describe, expect, it } from "vitest";
import { formatElapsed } from "./format";

describe("formatElapsed", () => {
  it("minutes:seconds, seconds padded", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(7_400)).toBe("0:07");
    expect(formatElapsed(187_000)).toBe("3:07");
    expect(formatElapsed(-5)).toBe("0:00");
  });
});
