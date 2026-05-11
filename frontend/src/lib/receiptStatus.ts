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
  QUEUED: "Oczekuje...",
  RUNNING: "Przetwarzanie...",
  OCR_OK: "Tekst odczytany",
  PARSING_OK: "Paragony sparsowane",
  CATEGORIZATION_OK: "Skategoryzowano",
  NEEDS_REVIEW: "Wymaga weryfikacji",
  FAILED: "Błąd przetwarzania",
  processing: "Przetwarzanie...",
  done: "Gotowe",
  error: "Błąd",
  needs_review: "Wymaga weryfikacji",
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
