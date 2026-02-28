import { describe, it, expect } from "vitest";
import { transactionSchema } from "@/components/dashboard/transaction/schema";

describe("transactionSchema (Zod)", () => {
  const validBase = {
    merchant_name: "Biedronka",
    currency: "PLN",
  };

  describe("merchant_name", () => {
    it("accepts a non-empty name", () => {
      const result = transactionSchema.safeParse(validBase);
      expect(result.success).toBe(true);
    });

    it("rejects empty name", () => {
      const result = transactionSchema.safeParse({ ...validBase, merchant_name: "" });
      expect(result.success).toBe(false);
    });
  });

  describe("total_amount", () => {
    it("accepts missing amount (optional field)", () => {
      const result = transactionSchema.safeParse(validBase);
      expect(result.success).toBe(true);
    });

    it("accepts positive amount", () => {
      const result = transactionSchema.safeParse({ ...validBase, total_amount: 49.99 });
      expect(result.success).toBe(true);
      if (result.success) expect(result.data.total_amount).toBe(49.99);
    });

    it("rejects amount of 0", () => {
      const result = transactionSchema.safeParse({ ...validBase, total_amount: 0 });
      expect(result.success).toBe(false);
    });

    it("rejects negative amount", () => {
      const result = transactionSchema.safeParse({ ...validBase, total_amount: -10 });
      expect(result.success).toBe(false);
    });

    it("coerces string to number", () => {
      const result = transactionSchema.safeParse({ ...validBase, total_amount: "25.50" });
      expect(result.success).toBe(true);
      if (result.success) expect(result.data.total_amount).toBe(25.5);
    });
  });

  describe("currency", () => {
    it("rejects empty currency", () => {
      const result = transactionSchema.safeParse({ ...validBase, currency: "" });
      expect(result.success).toBe(false);
    });

    it("accepts PLN, EUR, USD", () => {
      for (const currency of ["PLN", "EUR", "USD"]) {
        const result = transactionSchema.safeParse({ ...validBase, currency });
        expect(result.success).toBe(true);
      }
    });
  });

  describe("optional fields (category, note, date)", () => {
    it("accepts omitting all optional fields", () => {
      const result = transactionSchema.safeParse(validBase);
      expect(result.success).toBe(true);
    });

    it("accepts date as ISO string", () => {
      const result = transactionSchema.safeParse({ ...validBase, date: "2024-03-15" });
      expect(result.success).toBe(true);
    });
  });
});
