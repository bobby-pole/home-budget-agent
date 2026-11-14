export type DecimalInput = string | number | null | undefined;

const MONEY_SCALE = 2;
const UNIT_SCALE = 4;

const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

function pow10(scale: number): bigint {
  return 10n ** BigInt(scale);
}

/**
 * Normalize Polish/English decimal input strings into canonical dot-decimal syntax.
 * Supports spaces/NBSP thousand separators, unicode minus, and comma decimals.
 */
export function normalizeDecimalInput(value: DecimalInput): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }
    return String(value);
  }
  if (typeof value !== "string") {
    return null;
  }

  let cleaned = value
    .trim()
    .replace(/[\s\u00a0\u202f]+/g, "")
    .replace(/\u2212|\u2013/g, "-");

  if (!cleaned) {
    return null;
  }

  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  if (lastComma !== -1 && lastDot !== -1) {
    if (lastComma > lastDot) {
      cleaned = cleaned.replace(/\./g, "").replace(",", ".");
    } else {
      cleaned = cleaned.replace(/,/g, "");
    }
  } else if (lastComma !== -1) {
    const commaCount = cleaned.split(",").length - 1;
    if (commaCount !== 1) {
      return null;
    }
    cleaned = cleaned.replace(",", ".");
  }

  if (!DECIMAL_PATTERN.test(cleaned)) {
    return null;
  }
  return cleaned;
}

/**
 * Parse a decimal string/number into a scaled BigInt rounded HALF_UP to `scale` decimal digits.
 */
export function parseScaled(value: DecimalInput, scale: number): bigint | null {
  const normalized = normalizeDecimalInput(value);
  if (normalized === null) {
    return null;
  }

  let sign = 1n;
  let unsigned = normalized;
  if (unsigned.startsWith("-")) {
    sign = -1n;
    unsigned = unsigned.slice(1);
  } else if (unsigned.startsWith("+")) {
    unsigned = unsigned.slice(1);
  }

  const [intRaw = "0", fracRaw = ""] = unsigned.split(".");
  const intDigits = intRaw === "" ? "0" : intRaw;
  const paddedFrac = fracRaw.padEnd(scale + 1, "0");
  const keptFrac = paddedFrac.slice(0, scale);
  const nextDigit = Number(paddedFrac[scale] ?? "0");

  let magnitude = BigInt(intDigits) * pow10(scale) + BigInt(keptFrac || "0");
  if (nextDigit >= 5) {
    magnitude += 1n;
  }
  return magnitude === 0n ? 0n : sign * magnitude;
}

/**
 * Format a scaled BigInt into a canonical dot-decimal string.
 */
export function formatScaled(
  scaled: bigint,
  scale: number,
  minDecimals = scale
): string {
  const sign = scaled < 0n ? "-" : "";
  const abs = scaled < 0n ? -scaled : scaled;
  const factor = pow10(scale);
  const intPart = (abs / factor).toString();
  let fracPart = (abs % factor).toString().padStart(scale, "0");

  if (minDecimals < scale) {
    let trimmed = fracPart.replace(/0+$/, "");
    if (trimmed.length < minDecimals) {
      trimmed = fracPart.slice(0, minDecimals);
    }
    fracPart = trimmed;
  }

  return fracPart.length > 0 ? `${sign}${intPart}.${fracPart}` : `${sign}${intPart}`;
}

export function toCents(value: DecimalInput): bigint {
  return parseScaled(value, MONEY_SCALE) ?? 0n;
}

export function fromCents(cents: bigint): string {
  return formatScaled(cents, MONEY_SCALE, MONEY_SCALE);
}

export function parseMoneyInput(value: DecimalInput): string | null {
  const cents = parseScaled(value, MONEY_SCALE);
  return cents === null ? null : fromCents(cents);
}

export function parseUnitPriceInput(value: DecimalInput): string | null {
  const scaled = parseScaled(value, UNIT_SCALE);
  return scaled === null ? null : formatScaled(scaled, UNIT_SCALE, MONEY_SCALE);
}

export function parseQuantityInput(value: DecimalInput): string | null {
  const scaled = parseScaled(value, UNIT_SCALE);
  return scaled === null ? null : formatScaled(scaled, UNIT_SCALE, 0);
}

export function isValidDecimalInput(value: DecimalInput): boolean {
  return normalizeDecimalInput(value) !== null;
}

export function isPositiveMoneyInput(value: DecimalInput): boolean {
  const cents = parseScaled(value, MONEY_SCALE);
  return cents !== null && cents > 0n;
}

export function isPositiveDecimalInput(value: DecimalInput): boolean {
  const scaled = parseScaled(value, UNIT_SCALE);
  return scaled !== null && scaled > 0n;
}

export function isNonNegativeMoneyInput(value: DecimalInput): boolean {
  const cents = parseScaled(value, MONEY_SCALE);
  return cents !== null && cents >= 0n;
}

export function addMoney(...values: DecimalInput[]): string {
  let sum = 0n;
  for (const v of values) {
    sum += toCents(v);
  }
  return fromCents(sum);
}

export function subtractMoney(a: DecimalInput, b: DecimalInput): string {
  return fromCents(toCents(a) - toCents(b));
}

export function compareMoney(a: DecimalInput, b: DecimalInput): number {
  const diff = toCents(a) - toCents(b);
  if (diff < 0n) return -1;
  if (diff > 0n) return 1;
  return 0;
}

export function absMoney(value: DecimalInput): string {
  const c = toCents(value);
  return fromCents(c < 0n ? -c : c);
}

/**
 * Compute line total in cents with exact 4-decimal unit price * quantity math
 * rounded HALF_UP to 2 decimal places.
 */
export function computeLineGrossCents(
  price: DecimalInput,
  quantity: DecimalInput
): bigint {
  const p = parseScaled(price, UNIT_SCALE) ?? 0n;
  const q = parseScaled(quantity, UNIT_SCALE) ?? 0n;
  const product8 = p * q;
  const sign = product8 < 0n ? -1n : 1n;
  const abs8 = product8 < 0n ? -product8 : product8;
  // Convert 10^-8 to 10^-2: divide by 10^6 with HALF_UP rounding.
  const divisor = 1_000_000n;
  const remainder = abs8 % divisor;
  let centsAbs = abs8 / divisor;
  if (remainder >= divisor / 2n) {
    centsAbs += 1n;
  }
  return centsAbs === 0n ? 0n : sign * centsAbs;
}

export function computeLineTotal(
  price: DecimalInput,
  quantity: DecimalInput,
  discountTotal: DecimalInput = "0.00"
): string {
  const gross = computeLineGrossCents(price, quantity);
  const disc = toCents(discountTotal);
  return fromCents(gross + disc);
}

/**
 * Divide a 2-decimal monetary line total by a 4-decimal quantity, returning a
 * 4-decimal unit price string rounded HALF_UP.
 */
export function divideMoneyByQuantity(
  total: DecimalInput,
  quantity: DecimalInput
): string {
  const totalCents = toCents(total);
  const qtyScaled = parseScaled(quantity, UNIT_SCALE);
  if (qtyScaled === null || qtyScaled <= 0n) {
    return formatScaled(totalCents * 100n, UNIT_SCALE, MONEY_SCALE);
  }
  const sign = totalCents < 0n ? -1n : 1n;
  const numerator = (totalCents < 0n ? -totalCents : totalCents) * 1_000_000n;
  const quotient = numerator / qtyScaled;
  const remainder = numerator % qtyScaled;
  const rounded = remainder * 2n >= qtyScaled ? quotient + 1n : quotient;
  const signed = rounded === 0n ? 0n : sign * rounded;
  return formatScaled(signed, UNIT_SCALE, MONEY_SCALE);
}

export function formatMoneyFixed(value: DecimalInput): string {
  return fromCents(toCents(value));
}

/**
 * Format decimal currency amount using locale grouping and symbol without float rounding.
 */
export function formatCurrencyAmount(
  value: DecimalInput,
  currency = "PLN",
  locale = "pl-PL"
): string {
  const fixed = formatMoneyFixed(value);
  const isNeg = fixed.startsWith("-");
  const unsigned = isNeg ? fixed.slice(1) : fixed;
  const [intStr, fracStr] = unsigned.split(".");

  const intFormatted = new Intl.NumberFormat(locale, {
    useGrouping: true,
    maximumFractionDigits: 0,
  }).format(BigInt(intStr));

  const decimalSep = locale.startsWith("pl") ? "," : ".";
  const numStr = `${isNeg ? "-" : ""}${intFormatted}${decimalSep}${fracStr}`;
  return currency ? `${numStr} ${currency}` : numStr;
}

/**
 * Numeric adapter strictly for chart libraries (e.g. Recharts) that require JS numbers.
 */
export function toChartNumber(value: DecimalInput): number {
  const normalized = parseMoneyInput(value);
  return normalized ? Number(normalized) : 0;
}

/**
 * Format decimal money amount using Intl locale grouping without converting fractional cents to float.
 */
export function formatDecimalLocale(
  value: DecimalInput,
  locale = "pl-PL",
  options?: {
    minimumFractionDigits?: number;
    maximumFractionDigits?: number;
    currency?: string;
  }
): string {
  const fixed = formatMoneyFixed(value);
  const isNeg = fixed.startsWith("-");
  const unsigned = isNeg ? fixed.slice(1) : fixed;
  const [intStr, fracStr = "00"] = unsigned.split(".");

  const minFrac = Math.min(Math.max(options?.minimumFractionDigits ?? 2, 0), 2);
  const maxFrac = Math.min(Math.max(options?.maximumFractionDigits ?? 2, minFrac), 2);

  let renderedFrac = fracStr.slice(0, maxFrac);
  while (renderedFrac.length > minFrac && renderedFrac.endsWith("0")) {
    renderedFrac = renderedFrac.slice(0, -1);
  }

  const intFormatted = new Intl.NumberFormat(locale, {
    useGrouping: true,
    maximumFractionDigits: 0,
  }).format(BigInt(intStr));

  const decimalSep =
    new Intl.NumberFormat(locale)
      .formatToParts(1.1)
      .find((part) => part.type === "decimal")?.value ?? ",";

  const numStr = `${isNeg ? "-" : ""}${intFormatted}${
    renderedFrac.length > 0 ? `${decimalSep}${renderedFrac}` : ""
  }`;

  if (!options?.currency) {
    return numStr;
  }

  const currencySymbol =
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: options.currency,
    })
      .formatToParts(0)
      .find((part) => part.type === "currency")?.value ?? options.currency;

  return `${numStr}\u00a0${currencySymbol}`;
}
