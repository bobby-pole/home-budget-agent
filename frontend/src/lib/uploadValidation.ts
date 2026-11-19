import { t } from "@/lib/i18n";

export const MAX_BATCH_UPLOAD_FILES = 15;
export const MAX_PRIVATE_UPLOAD_BYTES = 10 * 1024 * 1024;
export const MAX_DEMO_UPLOAD_BYTES = 5 * 1024 * 1024;

const ALLOWED_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".pdf", ".json"]);
const ALLOWED_MIME_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
  "application/pdf",
  "application/json",
  "text/json",
]);

export interface ClientFileValidationResult {
  valid: boolean;
  reason?: string;
}

export function validateClientDocumentFile(
  file: File,
  isDemo: boolean = false
): ClientFileValidationResult {
  if (file.size <= 0) {
    return { valid: false, reason: t("upload.client_validation_empty") };
  }

  const maxBytes = isDemo ? MAX_DEMO_UPLOAD_BYTES : MAX_PRIVATE_UPLOAD_BYTES;
  const maxMb = Math.round(maxBytes / (1024 * 1024));
  if (file.size > maxBytes) {
    return {
      valid: false,
      reason: t("upload.client_validation_too_large", { limitMb: String(maxMb) }),
    };
  }

  const lowerName = file.name.toLowerCase();
  const dotIdx = lowerName.lastIndexOf(".");
  const ext = dotIdx >= 0 ? lowerName.slice(dotIdx) : "";
  const mime = (file.type || "").toLowerCase().split(";")[0].trim();

  const extOk = ext ? ALLOWED_EXTENSIONS.has(ext) : false;
  const mimeOk = mime ? ALLOWED_MIME_TYPES.has(mime) : false;

  if (!extOk && !mimeOk) {
    return { valid: false, reason: t("upload.client_validation_invalid_type") };
  }

  // Reject explicitly spoofed mismatches when both extension and MIME are provided
  if (mime && ext) {
    if (ext === ".pdf" && !mime.includes("pdf")) {
      return { valid: false, reason: t("upload.client_validation_invalid_type") };
    }
    if (ext === ".json" && !mime.includes("json")) {
      return { valid: false, reason: t("upload.client_validation_invalid_type") };
    }
    if ([".jpg", ".jpeg", ".png", ".webp"].includes(ext) && !mime.startsWith("image/")) {
      return { valid: false, reason: t("upload.client_validation_invalid_type") };
    }
  }

  return { valid: true };
}

export function formatFileSizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return t("upload.file_size_mb", { size: (bytes / (1024 * 1024)).toFixed(1) });
  }
  const kb = Math.max(1, Math.round(bytes / 1024));
  return t("upload.file_size_kb", { size: String(kb) });
}
