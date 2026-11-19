import { t } from "@/lib/i18n";

export function translateValidationMessage(message: string | null | undefined): string {
  if (!message) return "";
  const [code, ...rest] = message.split(":");
  const param = rest.join(":");
  switch (code) {
    case "RECEIPT_EMPTY":
      return t("errors.receipt.empty");
    case "RECEIPT_SUM_MISMATCH":
      return t("errors.receipt.sum_mismatch", { delta: param });
    case "RECEIPT_ZERO_PRICE_ITEM":
      return t("errors.receipt.zero_price_item");
    case "RECEIPT_FUTURE_DATE":
      return t("errors.receipt.future_date");
    case "DUPLICATE_REVIEW_REQUIRED":
      return t("errors.receipt.duplicate_review");
    case "VALIDATION_FAILED":
      return t("errors.receipt.validation_failed");
    case "LOW_CONFIDENCE":
      return t("errors.receipt.low_confidence");
    case "RECEIPT_UNKNOWN_ISSUE":
      return t("errors.receipt.unknown_issue");
    case "MISSING_ACCOUNT":
      return t("errors.receipt.missing_account");
    case "NEEDS_REVIEW":
      return t("errors.receipt.needs_review");
    case "TEXT_TOO_SHORT":
      return t("errors.receipt.text_too_short");
    case "MISSING_RECEIPT_KEYWORDS":
      return t("errors.receipt.missing_receipt_keywords");
    case "MISSING_PRICE_PATTERNS":
      return t("errors.receipt.missing_price_patterns");
    default:
      return message; // fallback: show original string (backward compat)
  }
}
