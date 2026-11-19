import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Database,
  ScanText,
  UserCheck,
} from "lucide-react";
import type { TransactionRead } from "@/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/dates";
import { translateValidationMessage } from "@/lib/errorCodes";
import { t } from "@/lib/i18n";
import {
  getEffectiveReviewReasons,
  getLiveSumComparison,
  getRetentionPolicyLabel,
  getTransactionProvenance,
} from "@/lib/provenance";
import { cn } from "@/lib/utils";

interface ProvenanceSummaryCardProps {
  transaction: TransactionRead;
  liveLinesTotal?: string;
  liveHeaderTotal?: string;
  defaultExpanded?: boolean;
  showReviewReasons?: boolean;
  className?: string;
}

function formatAcquiredTimestamp(raw: string | null): string | null {
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return formatDate(parsed, "dd MMM yyyy, HH:mm");
}

export function ProvenanceSummaryCard({
  transaction,
  liveLinesTotal,
  liveHeaderTotal,
  defaultExpanded = false,
  showReviewReasons = true,
  className,
}: ProvenanceSummaryCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const provenance = getTransactionProvenance(transaction);
  const reviewReasons = showReviewReasons ? getEffectiveReviewReasons(transaction) : [];
  const sumComparison = getLiveSumComparison(transaction, liveLinesTotal, liveHeaderTotal);
  const formattedAcquired = formatAcquiredTimestamp(provenance.acquiredAt);
  const retentionLabel = getRetentionPolicyLabel(provenance.rawPayloadPolicy);
  const currency = transaction.currency || "PLN";

  const hasMetadataDetails = Boolean(
    provenance.provider ||
      provenance.adapterVersion ||
      formattedAcquired ||
      provenance.processedVia ||
      provenance.externalId ||
      retentionLabel,
  );

  const ModeIcon =
    provenance.dataMode === "structured"
      ? Database
      : provenance.dataMode === "ocr"
        ? ScanText
        : UserCheck;

  const dataModeLabel =
    provenance.dataMode === "structured"
      ? t("provenance.kinds.structured")
      : provenance.dataMode === "ocr"
        ? t("provenance.kinds.ocr")
        : t("provenance.kinds.manual");

  return (
    <div className={cn("space-y-2.5", className)}>
      <div className="rounded-xl border border-border/60 bg-muted/25 p-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mr-1">
              {t("provenance.labels.section_title")}
            </span>

            {provenance.sourceLabel && (
              <Badge variant="secondary" className="text-[11px] font-semibold h-5 px-2">
                {provenance.sourceLabel}
              </Badge>
            )}

            <Badge
              variant="outline"
              className="text-[11px] font-medium h-5 px-2 gap-1 bg-background/60"
            >
              <ModeIcon className="h-3 w-3" />
              <span>{dataModeLabel}</span>
            </Badge>

            {provenance.dataMode === "ocr" && provenance.qualityPercent != null && (
              <Badge
                variant="outline"
                className={cn(
                  "text-[11px] font-medium h-5 px-2 tabular-nums",
                  provenance.qualityPercent >= 85
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30"
                    : "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30",
                )}
              >
                {t("provenance.labels.ocr_quality")}: {provenance.qualityPercent}%
              </Badge>
            )}

            {sumComparison.showVerifiedTotalBadge && (
              <Badge
                variant="outline"
                title={t("provenance.validation.sum_ok_tooltip")}
                className="text-[11px] font-semibold h-5 px-2 gap-1 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30"
              >
                <CheckCircle2 className="h-3 w-3" />
                <span>{t("provenance.validation.sum_ok")}</span>
              </Badge>
            )}

            {sumComparison.canonicalValid === true &&
              liveLinesTotal != null &&
              liveHeaderTotal != null &&
              !sumComparison.isExactMatch && (
                <Badge
                  variant="outline"
                  className="text-[11px] font-semibold h-5 px-2 gap-1 bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30 tabular-nums"
                >
                  <AlertTriangle className="h-3 w-3" />
                  <span>
                    {t("provenance.validation.sum_edited", {
                      delta: sumComparison.formattedAbsDiff,
                      currency,
                    })}
                  </span>
                </Badge>
              )}

            {sumComparison.canonicalValid === false && (
              <Badge
                variant="outline"
                className="text-[11px] font-semibold h-5 px-2 gap-1 bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30 tabular-nums"
              >
                <AlertTriangle className="h-3 w-3" />
                <span>
                  {sumComparison.diffCents !== 0n &&
                  (liveLinesTotal != null || (transaction.lines?.length ?? 0) > 0)
                    ? t("provenance.validation.sum_mismatch", {
                        delta: sumComparison.formattedAbsDiff,
                        currency,
                      })
                    : t("provenance.validation.sum_failed")}
                </span>
              </Badge>
            )}

            {sumComparison.canonicalValid === null && Boolean(transaction.receipt_scan) && (
              <Badge
                variant="outline"
                className="text-[11px] font-medium h-5 px-2 gap-1 bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/25"
              >
                <Clock className="h-3 w-3" />
                <span>{t("provenance.validation.sum_pending")}</span>
              </Badge>
            )}
          </div>

          {hasMetadataDetails && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={expanded}
              onClick={() => setExpanded((prev) => !prev)}
              className="h-6 px-2 text-[11px] text-muted-foreground hover:text-foreground gap-1"
            >
              <span>{t("provenance.labels.source_details_toggle")}</span>
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </Button>
          )}
        </div>

        {expanded && hasMetadataDetails && (
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 pt-2 border-t border-border/50 text-xs">
            {provenance.provider && (
              <div className="flex items-center justify-between sm:justify-start gap-2">
                <dt className="text-muted-foreground">{t("provenance.labels.provider")}:</dt>
                <dd className="font-mono font-medium text-foreground truncate">{provenance.provider}</dd>
              </div>
            )}
            {provenance.adapterVersion && (
              <div className="flex items-center justify-between sm:justify-start gap-2">
                <dt className="text-muted-foreground">{t("provenance.labels.adapter")}:</dt>
                <dd className="font-mono font-medium text-foreground truncate">{provenance.adapterVersion}</dd>
              </div>
            )}
            {formattedAcquired && (
              <div className="flex items-center justify-between sm:justify-start gap-2">
                <dt className="text-muted-foreground">{t("provenance.labels.acquired_at")}:</dt>
                <dd className="font-medium text-foreground tabular-nums">{formattedAcquired}</dd>
              </div>
            )}
            {provenance.processedVia &&
              provenance.processedVia !== provenance.adapterVersion && (
                <div className="flex items-center justify-between sm:justify-start gap-2">
                  <dt className="text-muted-foreground">{t("provenance.labels.processed_via")}:</dt>
                  <dd className="font-mono font-medium text-foreground truncate">{provenance.processedVia}</dd>
                </div>
              )}
            {provenance.externalId && (
              <div className="flex items-center justify-between sm:justify-start gap-2">
                <dt className="text-muted-foreground">{t("provenance.labels.external_id")}:</dt>
                <dd className="font-mono text-[11px] text-foreground truncate">{provenance.externalId}</dd>
              </div>
            )}
            {retentionLabel && (
              <div className="flex items-center justify-between sm:justify-start gap-2">
                <dt className="text-muted-foreground">{t("provenance.labels.retention")}:</dt>
                <dd className="font-medium text-foreground">{retentionLabel}</dd>
              </div>
            )}
            {provenance.dataMode === "structured" && (
              <div className="sm:col-span-2 text-[11px] text-emerald-700 dark:text-emerald-400 font-medium">
                {t("provenance.labels.structured_verified")}
              </div>
            )}
          </dl>
        )}
      </div>

      {reviewReasons.length > 0 && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-800 dark:text-amber-200"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
          <div className="space-y-1 min-w-0">
            <p className="font-semibold text-[11px] uppercase tracking-wider">
              {t("provenance.labels.review_reasons_title")}
            </p>
            <ul className="list-disc list-inside space-y-0.5">
              {reviewReasons.map((reason) => (
                <li key={reason}>{translateValidationMessage(reason)}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
