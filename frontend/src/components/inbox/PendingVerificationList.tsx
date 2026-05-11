import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dates";
import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";
import type { TransactionRead as Transaction } from "@/client";
import { getStatusLabel, getStatusVariant, isInProgress } from "@/lib/receiptStatus";
import { t } from "@/lib/i18n";

interface PendingVerificationListProps {
  transactions: Transaction[];
  selectedId?: number;
  onSelect: (transaction: Transaction) => void;
}

export function PendingVerificationList({ 
  transactions, 
  selectedId, 
  onSelect 
}: PendingVerificationListProps) {
  if (transactions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed rounded-2xl bg-muted/30">
        <CheckCircle2 className="h-12 w-12 text-muted-foreground/30 mb-4" />
        <h3 className="text-lg font-medium text-muted-foreground">{t("inbox.list.all_checked_title")}</h3>
        <p className="text-sm text-muted-foreground/60 max-w-[200px]">
          {t("inbox.list.all_checked_description")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {transactions.map((tx) => {
        const isSelected = selectedId === tx.id;
        const status = tx.receipt_scan?.status || "processing";
        const variant = getStatusVariant(status);
        const label = getStatusLabel(status);
        const inProgress = isInProgress(status);

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
              <div className="flex justify-between items-start gap-2">
                <div className="min-w-0">
                  <h4 className="font-semibold text-sm truncate">
                    {tx.merchant_name || t("inbox.list.processing_placeholder")}
                  </h4>
                  <p className="text-xs text-muted-foreground mt-1">
                    {tx.date ? formatDate(tx.date, "PPP") : t("inbox.list.no_date")}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-bold">
                    {(tx.total_amount ?? 0).toFixed(2)} {tx.currency}
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
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
