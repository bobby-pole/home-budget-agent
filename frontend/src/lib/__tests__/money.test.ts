import { describe, expect, it } from "vitest";
import {
  absMoney,
  addMoney,
  compareMoney,
  computeLineTotal,
  divideMoneyByQuantity,
  formatCurrencyAmount,
  formatDecimalLocale,
  formatMoneyFixed,
  isNonNegativeMoneyInput,
  isPositiveDecimalInput,
  isPositiveMoneyInput,
  normalizeDecimalInput,
  parseMoneyInput,
  parseQuantityInput,
  parseUnitPriceInput,
  subtractMoney,
  toChartNumber,
} from "../money";

describe("money decimal helpers", () => {
  it("normalizes Polish commas, spaces, NBSP, and unicode minus", () => {
    expect(normalizeDecimalInput("1 234,56")).toBe("1234.56");
    expect(normalizeDecimalInput("2\u00a0500,05")).toBe("2500.05");
    expect(normalizeDecimalInput("\u221242,90")).toBe("-42.90");
    expect(normalizeDecimalInput("1,234.56")).toBe("1234.56");
    expect(normalizeDecimalInput("1.234,56")).toBe("1234.56");
    expect(normalizeDecimalInput("abc")).toBeNull();
    expect(normalizeDecimalInput("")).toBeNull();
    expect(normalizeDecimalInput(Number.NaN)).toBeNull();
  });

  it("avoids binary IEEE-754 drift in addition and subtraction", () => {
    expect(addMoney("0.10", "0.20")).toBe("0.30");
    expect(addMoney("10.99", "0.01", "-1.00")).toBe("10.00");
    expect(subtractMoney("100.00", "99.99")).toBe("0.01");
    expect(compareMoney("0.30", "0.3")).toBe(0);
    expect(compareMoney("10.01", "10.00")).toBe(1);
    expect(absMoney("-12.34")).toBe("12.34");
  });

  it("preserves 4-decimal unit prices and fractional quantities", () => {
    expect(parseUnitPriceInput("3.9943")).toBe("3.9943");
    expect(parseUnitPriceInput("10,5")).toBe("10.50");
    expect(parseQuantityInput("1,976")).toBe("1.976");
    expect(parseQuantityInput("2.0000")).toBe("2");
    expect(parseMoneyInput("10.125")).toBe("10.13");
    expect(computeLineTotal("3.9943", "1.976")).toBe("7.89");
    expect(computeLineTotal("4.13", "1.976", "-0.27")).toBe("7.89");
  });

  it("validates positive and non-negative inputs cleanly", () => {
    expect(isPositiveMoneyInput("0,01")).toBe(true);
    expect(isPositiveMoneyInput("0,00")).toBe(false);
    expect(isPositiveDecimalInput("0,001")).toBe(true);
    expect(isNonNegativeMoneyInput("0")).toBe(true);
    expect(isNonNegativeMoneyInput("-0.01")).toBe(false);
  });

  it("formats display currency without float errors and adapts cleanly for charts", () => {
    expect(formatMoneyFixed("125.5")).toBe("125.50");
    expect(formatCurrencyAmount("1234.56", "PLN", "pl-PL")).toContain("234,56 PLN");
    expect(toChartNumber("19.99")).toBe(19.99);
    expect(toChartNumber("invalid")).toBe(0);
  });

  it("divides line totals by fractional quantities using HALF_UP to 4 decimals", () => {
    expect(divideMoneyByQuantity("9.99", "3")).toBe("3.33");
    expect(divideMoneyByQuantity("10.00", "3")).toBe("3.3333");
    expect(divideMoneyByQuantity("20.00", "3")).toBe("6.6667");
    expect(divideMoneyByQuantity("-5.00", "2")).toBe("-2.50");
  });

  it("formats locale decimal and currency output using BigInt without float drift", () => {
    expect(formatDecimalLocale("42.50", "pl-PL")).toBe("42,50");
    expect(formatDecimalLocale("1200.00", "pl-PL", { currency: "PLN" })).toMatch(/1.*200,00\s+zł/);
    expect(formatDecimalLocale("-500.00", "pl-PL", { currency: "PLN" })).toMatch(/-500,00\s+zł/);
    expect(
      formatDecimalLocale("200.00", "pl-PL", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      })
    ).toBe("200");
    expect(
      formatDecimalLocale("12.50", "pl-PL", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      })
    ).toBe("12,5");
  });
});
