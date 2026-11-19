import type { SourceRecordRead, TransactionRead } from "@/client";
import { t } from "@/lib/i18n";
import { formatMoneyFixed, subtractMoney, toCents } from "@/lib/money";

export type SourceDataMode = "structured" | "ocr" | "manual";
export type NormalizedCategorySource = "cache" | "ai" | "user" | "auto" | null;

export interface TransactionProvenanceSummary {
  primarySource: SourceRecordRead | null;
  sources: SourceRecordRead[];
  sourceLabel: string | null;
  provider: string | null;
  adapterVersion: string | null;
  acquiredAt: string | null;
  processedVia: string | null;
  externalId: string | null;
  dataMode: SourceDataMode;
  qualityPercent: number | null;
  rawPayloadPolicy: string | null;
  isExternalImport: boolean;
}

export interface CategorySourceMeta {
  kind: Exclude<NormalizedCategorySource, null>;
  label: string;
  tooltip: string;
  badgeClass: string;
}

export interface LiveSumComparison {
  canonicalValid: boolean | null;
  isExactMatch: boolean;
  diffCents: bigint;
  formattedAbsDiff: string;
  showVerifiedTotalBadge: boolean;
}

const STRUCTURED_SOURCE_TYPES = new Set([
  "MERCHANT_API",
  "E_RECEIPT",
  "BANK_CSV",
]);

const EXTERNAL_PRESERVE_SOURCE_TYPES = new Set([
  "BANK_CSV",
  "MERCHANT_API",
  "E_RECEIPT",
]);

const SOURCE_PRIORITY: Record<string, number> = {
  MERCHANT_API: 5,
  E_RECEIPT: 4,
  BANK_CSV: 3,
  OCR_PHOTO: 2,
  MANUAL: 1,
};

const IN_PROGRESS_SCAN_STATUSES = new Set([
  "QUEUED",
  "RUNNING",
  "OCR_OK",
  "PARSING_OK",
  "processing",
]);

function pickPrimarySource(sources: SourceRecordRead[]): SourceRecordRead | null {
  if (!sources.length) return null;
  return [...sources].sort((a, b) => {
    const pa = SOURCE_PRIORITY[String(a.source_type || "").toUpperCase()] ?? 0;
    const pb = SOURCE_PRIORITY[String(b.source_type || "").toUpperCase()] ?? 0;
    return pb - pa;
  })[0];
}

export function getSourceRecordBadgeLabel(
  source: SourceRecordRead | undefined | null,
  isManual?: boolean,
): string | null {
  if (!source) {
    return isManual ? t("provenance.sources.manual") : null;
  }
  const srcType = String(source.source_type || "").toUpperCase();
  if (srcType === "MERCHANT_API") {
    return source.provider === "lidl"
      ? t("provenance.sources.lidl")
      : t("provenance.sources.merchant_api");
  }
  if (srcType === "E_RECEIPT") return t("provenance.sources.e_receipt");
  if (srcType === "BANK_CSV") return t("provenance.sources.bank_csv");
  if (srcType === "OCR_PHOTO") return t("provenance.sources.ocr_photo");
  if (srcType === "MANUAL") return t("provenance.sources.manual");
  return source.provider || t("provenance.sources.unknown");
}

export function hasExternalImportSource(
  transaction: TransactionRead | undefined | null,
): boolean {
  if (!transaction?.source_records?.length) return false;
  return transaction.source_records.some((sr) =>
    EXTERNAL_PRESERVE_SOURCE_TYPES.has(String(sr.source_type || "").toUpperCase()),
  );
}

export function getDataMode(
  primarySource: SourceRecordRead | null,
  transaction: TransactionRead,
): SourceDataMode {
  if (primarySource) {
    const srcType = String(primarySource.source_type || "").toUpperCase();
    if (STRUCTURED_SOURCE_TYPES.has(srcType)) {
      return "structured";
    }
    if (srcType === "OCR_PHOTO") {
      return "ocr";
    }
    if (srcType === "MANUAL") {
      return "manual";
    }
  }
  if (transaction.receipt_scan) {
    return "ocr";
  }
  return "manual";
}

function parseQualityPercent(
  rawQuality: string | number | null | undefined,
  dataMode: SourceDataMode,
): number | null {
  // Never synthesize or display OCR/AI confidence percentages for deterministic structured data.
  if (dataMode !== "ocr" || rawQuality == null) {
    return null;
  }
  const parsed = Number(rawQuality);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  const pct = parsed <= 1 ? Math.round(parsed * 100) : Math.round(parsed);
  return Math.max(0, Math.min(100, pct));
}

export function getTransactionProvenance(
  transaction: TransactionRead,
): TransactionProvenanceSummary {
  const sources = transaction.source_records ?? [];
  const primarySource = pickPrimarySource(sources);
  const dataMode = getDataMode(primarySource, transaction);
  const sourceLabel = getSourceRecordBadgeLabel(primarySource, transaction.is_manual);

  return {
    primarySource,
    sources,
    sourceLabel,
    provider: primarySource?.provider ?? null,
    adapterVersion: primarySource?.adapter_version ?? null,
    acquiredAt: primarySource?.acquired_at ?? transaction.receipt_scan?.created_at ?? null,
    processedVia: transaction.receipt_scan?.processed_via ?? null,
    externalId: primarySource?.external_id ?? null,
    dataMode,
    qualityPercent: parseQualityPercent(primarySource?.quality, dataMode),
    rawPayloadPolicy: primarySource?.raw_payload_policy ?? null,
    isExternalImport: hasExternalImportSource(transaction),
  };
}

export function getRetentionPolicyLabel(policy?: string | null): string | null {
  if (!policy) return null;
  switch (policy) {
    case "retained_image":
      return t("provenance.labels.retention_retained_image");
    case "ephemeral_image":
      return t("provenance.labels.retention_ephemeral_image");
    case "canonical_only":
      return t("provenance.labels.retention_canonical_only");
    case "none":
      return t("provenance.labels.retention_none");
    default:
      return policy;
  }
}

export function normalizeCategorySource(
  raw: string | null | undefined,
): NormalizedCategorySource {
  const val = String(raw || "").trim().toLowerCase();
  if (!val) return null;
  if (val === "cache") return "cache";
  if (val === "ai") return "ai";
  if (val === "user" || val === "manual") return "user";
  if (val === "auto_categorizer" || val === "demo_fixture" || val === "auto") return "auto";
  return null;
}

export function getCategorySourceMeta(
  raw: string | null | undefined,
): CategorySourceMeta | null {
  const kind = normalizeCategorySource(raw);
  if (!kind) return null;

  switch (kind) {
    case "cache":
      return {
        kind,
        label: t("provenance.category_source.cache"),
        tooltip: t("provenance.category_source.cache_tooltip"),
        badgeClass:
          "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25",
      };
    case "ai":
      return {
        kind,
        label: t("provenance.category_source.ai"),
        tooltip: t("provenance.category_source.ai_tooltip"),
        badgeClass:
          "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-500/25",
      };
    case "user":
      return {
        kind,
        label: t("provenance.category_source.user"),
        tooltip: t("provenance.category_source.user_tooltip"),
        badgeClass:
          "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/25",
      };
    case "auto":
      return {
        kind,
        label: t("provenance.category_source.auto"),
        tooltip: t("provenance.category_source.auto_tooltip"),
        badgeClass:
          "bg-muted text-muted-foreground border-border",
      };
  }
}

export function getEffectiveReviewReasons(transaction: TransactionRead): string[] {
  const reasons: string[] = [];
  const pushUnique = (code: string | null | undefined) => {
    const cleaned = String(code || "").trim();
    if (cleaned && !reasons.includes(cleaned)) {
      reasons.push(cleaned);
    }
  };

  if (transaction.review_reasons && transaction.review_reasons.length > 0) {
    for (const reason of transaction.review_reasons) {
      pushUnique(reason);
    }
    return reasons;
  }

  const scan = transaction.receipt_scan;
  const scanStatus = String(scan?.status || "");
  const inProgress = Boolean(scan && IN_PROGRESS_SCAN_STATUSES.has(scanStatus));
  const finalized = Boolean(scan && (scanStatus === "DONE" || scanStatus === "done"));

  if (scan && !inProgress) {
    if (scanStatus === "FAILED" || scanStatus === "error") {
      pushUnique(scan.validation_message || scan.error_message || "VALIDATION_FAILED");
    } else if (scan.validation_message && !finalized) {
      pushUnique(scan.validation_message);
    }
  }

  if (
    transaction.account_id == null &&
    transaction.review_status === "pending" &&
    !inProgress
  ) {
    pushUnique("MISSING_ACCOUNT");
  }

  if (
    reasons.length === 0 &&
    !inProgress &&
    (transaction.review_status === "pending" || (scan?.needs_review && !finalized))
  ) {
    pushUnique("NEEDS_REVIEW");
  }

  return reasons;
}

export function getLiveSumComparison(
  transaction: TransactionRead,
  liveLinesTotal?: string,
  liveHeaderTotal?: string,
): LiveSumComparison {
  const canonicalValid = transaction.canonical_total_valid ?? null;
  const lhs = liveLinesTotal ?? transaction.total_amount ?? "0.00";
  const rhs = liveHeaderTotal ?? transaction.total_amount ?? "0.00";
  const diffStr = subtractMoney(lhs, rhs);
  const diffCents = toCents(diffStr);
  const absDiffCents = diffCents < 0n ? -diffCents : diffCents;
  const isExactMatch = absDiffCents <= 1n;
  const formattedAbsDiff = formatMoneyFixed(
    diffCents < 0n ? diffStr.replace("-", "") : diffStr,
  );

  // Successful total check is only shown when backend canonical receipt validation passed
  // AND any current unsaved form values still agree within ±0.01 PLN.
  const showVerifiedTotalBadge =
    canonicalValid === true &&
    (liveLinesTotal == null || liveHeaderTotal == null || isExactMatch);

  return {
    canonicalValid,
    isExactMatch,
    diffCents,
    formattedAbsDiff,
    showVerifiedTotalBadge,
  };
}
