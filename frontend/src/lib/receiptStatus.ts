import { t } from "@/lib/i18n";

export type ReceiptStatus =
  | "QUEUED"
  | "RUNNING"
  | "OCR_OK"
  | "PARSING_OK"
  | "CATEGORIZATION_OK"
  | "NEEDS_REVIEW"
  | "FAILED"
  | "processing"
  | "done"
  | "error"
  | "needs_review";

export type StatusVariant = "in-progress" | "success" | "warning" | "error";

export const STATUS_LABELS: Record<string, string> = {
  QUEUED: t("receipt_status.queued"),
  RUNNING: t("receipt_status.running"),
  OCR_OK: t("receipt_status.ocr_ok"),
  PARSING_OK: t("receipt_status.parsing_ok"),
  CATEGORIZATION_OK: t("receipt_status.categorization_ok"),
  NEEDS_REVIEW: t("receipt_status.needs_review"),
  FAILED: t("receipt_status.failed"),
  processing: t("receipt_status.processing"),
  done: t("receipt_status.done"),
  error: t("receipt_status.error"),
  needs_review: t("receipt_status.needs_review"),
};

export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function getStatusVariant(status: string): StatusVariant {
  if (["QUEUED", "RUNNING", "OCR_OK", "PARSING_OK"].includes(status)) return "in-progress";
  if (["CATEGORIZATION_OK", "done"].includes(status)) return "success";
  if (["NEEDS_REVIEW", "needs_review"].includes(status)) return "warning";
  if (["FAILED", "error"].includes(status)) return "error";
  return "in-progress";
}

export function isInProgress(status: string): boolean {
  return ["QUEUED", "RUNNING", "OCR_OK", "PARSING_OK", "processing"].includes(status);
}
