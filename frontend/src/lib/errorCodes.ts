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
    default:
      return message; // fallback: show original string (backward compat)
  }
}
