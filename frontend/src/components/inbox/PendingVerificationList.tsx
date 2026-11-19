import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dates";
import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";
import type { TransactionRead as Transaction } from "@/client";
import { translateValidationMessage } from "@/lib/errorCodes";
import {
  getEffectiveReviewReasons,
  getLiveSumComparison,
  getTransactionProvenance,
} from "@/lib/provenance";
import { getStatusLabel, getStatusVariant, isInProgress } from "@/lib/receiptStatus";
import { t } from "@/lib/i18n";
import { formatMoneyFixed } from "@/lib/money";

interface PendingVerificationListProps {
  transactions: Transaction[];
  selectedId?: number;
  selectedIds?: number[];
  onToggleSelect?: (id: number) => void;
  onSelect: (transaction: Transaction) => void;
}

export function PendingVerificationList({
  transactions,
  selectedId,
  selectedIds = [],
  onToggleSelect,
  onSelect,
}: PendingVerificationListProps) {
  if (transactions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed rounded-2xl bg-muted/30">
        <CheckCircle2 className="h-12 w-12 text-muted-foreground/30 mb-4" />
        <h3 className="text-lg font-medium text-muted-foreground">{t("inbox.list.all_checked_title")}</h3>
        <p className="text-sm text-muted-foreground/60 max-w-[220px]">
          {t("inbox.list.all_checked_description")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {transactions.map((tx) => {
        const isSelected = selectedId === tx.id;
        const isChecked = selectedIds.includes(tx.id);
        const hasScan = Boolean(tx.receipt_scan);
        const status = tx.receipt_scan?.status || (tx.account_id == null ? "NEEDS_REVIEW" : "processing");
        const variant = hasScan ? getStatusVariant(status) : "warning";
        const label = hasScan ? getStatusLabel(status) : t("inbox.list.missing_account_hint");
        const inProgress = hasScan && isInProgress(status);
        const provenance = getTransactionProvenance(tx);
        const sourceLabel = provenance.sourceLabel;
        const reviewReasons = getEffectiveReviewReasons(tx);
        const sumComparison = getLiveSumComparison(tx);

        return (
          <Card
            key={tx.id}
            className={cn(
              "cursor-pointer transition-all duration-200 hover:border-primary/50 hover:shadow-md border-border/50",
              isSelected ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "bg-card/50"
            )}
            onClick={() => onSelect(tx)}
          >
            <CardContent className="p-4">
              <div className="flex items-start gap-2.5">
                {onToggleSelect && (
                  <div
                    className="pt-0.5 shrink-0"
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => onToggleSelect(tx.id)}
                      aria-label={tx.merchant_name || `tx-${tx.id}`}
                      className="h-4 w-4 rounded border-border accent-primary cursor-pointer"
                    />
                  </div>
                )}
                <div className="flex-1 flex justify-between items-start gap-2 min-w-0">
                  <div className="min-w-0">
                    <h4 className="font-semibold text-sm truncate">
                      {tx.merchant_name || t("inbox.list.processing_placeholder")}
                    </h4>
                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                      <p className="text-xs text-muted-foreground">
                        {tx.date ? formatDate(tx.date, "PPP") : t("inbox.list.no_date")}
                      </p>
                      {sourceLabel && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                          {sourceLabel}
                        </Badge>
                      )}
                      {sumComparison.showVerifiedTotalBadge && (
                        <Badge
                          variant="outline"
                          className="text-[10px] h-4 px-1.5 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25 gap-0.5"
                        >
                          <CheckCircle2 className="h-2.5 w-2.5" />
                          <span>{t("provenance.validation.sum_ok")}</span>
                        </Badge>
                      )}
                    </div>
                    {reviewReasons.length > 0 && (
                      <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-300 line-clamp-2">
                        {translateValidationMessage(reviewReasons[0])}
                      </p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-bold">
                      {formatMoneyFixed(tx.total_amount ?? "0.00")} {tx.currency}
                    </div>
                    <div className="mt-2 flex justify-end">
                      {variant === "in-progress" && (
                        <Badge variant="secondary" className="text-[10px] h-5 bg-blue-500/10 text-blue-500 border-blue-500/20 gap-1">
                          {inProgress ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Clock className="h-3 w-3 animate-pulse" />
                          )}
                          {label}
                        </Badge>
                      )}
                      {variant === "success" && (
                        <Badge variant="outline" className="text-[10px] h-5 bg-green-500/10 text-green-600 border-green-500/20 gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          {label}
                        </Badge>
                      )}
                      {variant === "warning" && (
                        <Badge variant="outline" className="text-[10px] h-5 bg-amber-500/10 text-amber-500 border-amber-500/20 gap-1">
                          <AlertCircle className="h-3 w-3" />
                          {label}
                        </Badge>
                      )}
                      {variant === "error" && (
                        <Badge variant="destructive" className="text-[10px] h-5 gap-1">
                          <AlertCircle className="h-3 w-3" />
                          {label}
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
