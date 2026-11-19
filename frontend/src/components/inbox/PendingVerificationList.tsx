import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dates";
import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";
import type { TransactionRead as Transaction } from "@/client";
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

function getSourceBadge(tx: Transaction): string | null {
  const first = tx.source_records?.[0];
  if (!first) return null;
  const st = String(first.source_type || "").toUpperCase();
  if (st === "OCR_PHOTO") return t("inbox.list.source_ocr_photo");
  if (st === "MERCHANT_API") {
    return first.provider === "lidl" ? "Lidl Plus" : t("inbox.list.source_merchant_api");
  }
  if (st === "E_RECEIPT") return t("inbox.list.source_e_receipt");
  if (st === "BANK_CSV") return t("inbox.list.source_bank_csv");
  if (st === "MANUAL") return t("inbox.list.source_manual");
  return null;
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
        const sourceLabel = getSourceBadge(tx);

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
                    </div>
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
