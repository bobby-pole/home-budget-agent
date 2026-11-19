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
    case "OCR_TRANSIENT_ERROR":
      return t("errors.receipt.ocr_transient_error");
    case "OCR_NO_DATA":
      return t("errors.receipt.ocr_no_data");
    case "FILE_NOT_FOUND":
      return t("errors.receipt.file_not_found");
    case "DUPLICATE_FILE":
      return t("errors.receipt.duplicate_file");
    case "UPLOAD_TOO_LARGE":
    case "FILE_TOO_LARGE":
      return t("errors.receipt.upload_too_large");
    case "UNSUPPORTED_FILE_TYPE":
      return t("errors.receipt.unsupported_file_type");
    case "INVALID_FILE_SIGNATURE":
      return t("errors.receipt.invalid_file_signature");
    case "MAGIC_BYTE_MISMATCH":
    case "FILE_SIGNATURE_MISMATCH":
      return t("errors.receipt.magic_byte_mismatch");
    case "UPLOAD_RATE_LIMITED":
      return t("errors.receipt.upload_rate_limited");
    case "UPLOAD_QUEUE_FULL":
      return t("errors.receipt.upload_queue_full");
    case "DEMO_DAILY_LIMIT_EXCEEDED":
      return t("errors.receipt.demo_daily_limit_exceeded");
    case "INVALID_DOCUMENT_JOB":
      return t("errors.receipt.invalid_document_job");
    case "DOCUMENT_INGEST_FAILED":
      return t("errors.receipt.document_ingest_failed");
    case "EMPTY_FILE":
      return t("errors.receipt.empty_file");
    case "CORRUPT_DOCUMENT":
      return t("errors.receipt.corrupt_document");
    default:
      return message; // fallback: show original string (backward compat)
  }
}
