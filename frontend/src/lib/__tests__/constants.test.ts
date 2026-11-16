import { describe, it, expect, afterEach } from "vitest";
import {
  CATEGORIES,
  CATEGORY_HEX_COLORS,
  getCategoryDisplayName,
} from "@/lib/constants";
import { getLocale, setLocale } from "@/lib/i18n";

describe("getCategoryDisplayName", () => {
  const originalLocale = getLocale();

  afterEach(() => {
    setLocale(originalLocale);
  });

  it("translates every main CATEGORY in both PL and EN", () => {
    setLocale("pl");
    for (const cat of CATEGORIES) {
      expect(getCategoryDisplayName({ name: cat, is_system: true })).toBeTruthy();
    }
    expect(getCategoryDisplayName({ name: "Food", is_system: true })).toBe("Jedzenie");
    expect(getCategoryDisplayName({ name: "Housing", is_system: true })).toBe("Dom");
    expect(getCategoryDisplayName({ name: "Other", is_system: true })).toBe("Inne");
    expect(getCategoryDisplayName({ name: "Transport", is_system: true })).toBe("Transport");

    setLocale("en");
    expect(getCategoryDisplayName({ name: "Food", is_system: true })).toBe("Food");
    expect(getCategoryDisplayName({ name: "Housing", is_system: true })).toBe("Housing");
    expect(getCategoryDisplayName({ name: "Other", is_system: true })).toBe("Other");
  });

  it("preserves user-created category names regardless of active locale", () => {
    setLocale("pl");
    expect(getCategoryDisplayName({ name: "Moja kategoria", is_system: false })).toBe("Moja kategoria");
    expect(getCategoryDisplayName({ name: "Food", is_system: false })).toBe("Food");

    setLocale("en");
    expect(getCategoryDisplayName({ name: "Kawa specialty", is_system: false })).toBe("Kawa specialty");
  });

  it("handles null/undefined with optional fallback", () => {
    expect(getCategoryDisplayName(null, "Brak")).toBe("Brak");
    expect(getCategoryDisplayName(undefined)).toBe("");
  });
});

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

describe("CATEGORY_HEX_COLORS", () => {
  it("provides a hex color for every main category", () => {
    for (const cat of CATEGORIES) {
      const color = CATEGORY_HEX_COLORS[cat];
      expect(color).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });
});
