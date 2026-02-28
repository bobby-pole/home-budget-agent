import { describe, it, expect } from "vitest";
import { CATEGORIES, CATEGORY_LABELS, CATEGORY_HEX_COLORS } from "@/lib/constants";

describe("CATEGORIES", () => {
  it("contains expected main categories", () => {
    expect(CATEGORIES).toContain("Food");
    expect(CATEGORIES).toContain("Transport");
    expect(CATEGORIES).toContain("Other");
    expect(CATEGORIES).toContain("Entertainment");
  });

  it("has no duplicates", () => {
    const unique = new Set(CATEGORIES);
    expect(unique.size).toBe(CATEGORIES.length);
  });

  it("is a non-empty array", () => {
    expect(CATEGORIES.length).toBeGreaterThan(0);
  });
});

describe("CATEGORY_LABELS", () => {
  it("maps every main CATEGORY to a Polish label", () => {
    for (const cat of CATEGORIES) {
      expect(CATEGORY_LABELS[cat]).toBeTruthy();
    }
  });

  it("Food maps to 'Jedzenie'", () => {
    expect(CATEGORY_LABELS["Food"]).toBe("Jedzenie");
  });

  it("Other maps to 'Inne'", () => {
    expect(CATEGORY_LABELS["Other"]).toBe("Inne");
  });

  it("Transport maps to 'Transport'", () => {
    expect(CATEGORY_LABELS["Transport"]).toBe("Transport");
  });
});

describe("CATEGORY_HEX_COLORS", () => {
  it("provides a hex color for every main category", () => {
    for (const cat of CATEGORIES) {
      const color = CATEGORY_HEX_COLORS[cat];
      expect(color).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });
});
