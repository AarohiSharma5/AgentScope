import { describe, expect, it } from "vitest";
import { fmtCost, fmtDuration, fmtLatency, fmtNumber, fmtScore } from "./format.js";

describe("format helpers", () => {
  it("fmtScore renders 3 decimals or an em dash", () => {
    expect(fmtScore(0.28867)).toBe("0.289");
    expect(fmtScore(1)).toBe("1.000");
    expect(fmtScore(null)).toBe("—");
    expect(fmtScore(undefined)).toBe("—");
  });

  it("fmtLatency scales ms to seconds past 1000ms", () => {
    expect(fmtLatency(250)).toBe("250ms");
    expect(fmtLatency(1500)).toBe("1.50s");
    expect(fmtLatency(null)).toBe("—");
  });

  it("fmtCost formats to 4 decimals", () => {
    expect(fmtCost(0.0012)).toBe("$0.0012");
    expect(fmtCost(null)).toBe("—");
  });

  it("fmtNumber groups and rounds", () => {
    expect(fmtNumber(1234)).toBe("1,234");
    expect(fmtNumber(null)).toBe("—");
  });

  it("fmtDuration computes elapsed between ISO timestamps", () => {
    expect(fmtDuration("2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.250Z")).toBe("250ms");
    expect(fmtDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z")).toBe("1.00s");
    expect(fmtDuration(null, "2026-01-01T00:00:01Z")).toBe("—");
  });
});
