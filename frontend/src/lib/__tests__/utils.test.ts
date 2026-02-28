import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn()", () => {
  it("returns a single class unchanged", () => {
    expect(cn("text-red-500")).toBe("text-red-500");
  });

  it("merges multiple classes", () => {
    expect(cn("px-2", "py-1")).toBe("px-2 py-1");
  });

  it("resolves Tailwind conflicts — last class wins", () => {
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
    expect(cn("p-4", "p-2")).toBe("p-2");
  });

  it("handles conditional classes (falsy values ignored)", () => {
    expect(cn("base", false && "ignored", undefined, null, "visible")).toBe(
      "base visible"
    );
  });

  it("handles object syntax", () => {
    expect(cn({ "font-bold": true, "font-light": false })).toBe("font-bold");
  });

  it("handles array syntax", () => {
    expect(cn(["text-sm", "rounded"])).toBe("text-sm rounded");
  });

  it("returns empty string for no arguments", () => {
    expect(cn()).toBe("");
  });
});
