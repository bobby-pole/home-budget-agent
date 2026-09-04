import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Store, ArrowRight, ArrowUpRight, ArrowDownRight, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { TransactionRead, CategoryRead } from "@/client";
import { cn } from "@/lib/utils";
import { getIntlLocale } from "@/lib/dates";
import { useAuth } from "@/context/AuthContext";
import { CATEGORY_LABELS } from "@/lib/constants";
import { t } from "@/lib/i18n";
import { CategoryIcon } from "@/components/CategoryIcon";

interface RecentTransactionsListProps {
  transactions: TransactionRead[];
  categories?: CategoryRead[];
  isLoading: boolean;
  selectedAccountId?: number | null;
  selectedAccountName?: string;
  onClearAccountFilter?: () => void;
}

function formatRelativeDate(dateString: string | null | undefined): string {
  if (!dateString) return t("dashboard.recent_transactions.no_date");
  
  const date = new Date(dateString);
  const now = new Date();
  
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();

  if (isToday) return t("dashboard.recent_transactions.today");
  if (isYesterday) return t("dashboard.recent_transactions.yesterday");
  
  return date.toLocaleDateString(getIntlLocale(), { day: "numeric", month: "short" });
}

export function RecentTransactionsList({
  transactions,
  categories = [],
  isLoading,
  selectedAccountId,
  selectedAccountName,
  onClearAccountFilter,
}: RecentTransactionsListProps) {
  const { user } = useAuth();

  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm h-[400px] bg-card animate-pulse" />
    );
  }

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-bold">{t("dashboard.recent_transactions.title")}</CardTitle>
        <Button variant="ghost" size="sm" asChild className="text-primary font-bold rounded-full">
          <Link to={selectedAccountId ? `/transactions?accountId=${selectedAccountId}` : "/transactions"}>
            {t("dashboard.recent_transactions.all_link")} <ArrowRight className="ml-1 size-4" />
          </Link>
        </Button>
      </CardHeader>
      {selectedAccountId && selectedAccountName && (
        <div className="flex items-center justify-between px-6 py-2 bg-primary/10 text-primary text-xs font-medium border-b border-border/40">
          <span>
            {t("dashboard.recent_transactions.filter_active_prefix")}{" "}
            <strong>{selectedAccountName}</strong>
          </span>
          {onClearAccountFilter && (
            <button
              type="button"
              onClick={onClearAccountFilter}
              className="text-muted-foreground hover:text-foreground flex items-center gap-1 font-bold cursor-pointer"
            >
              <X className="size-3" />
              {t("dashboard.recent_transactions.clear_filter")}
            </button>
          )}
        </div>
      )}
      <CardContent className="px-0">
        <div className="divide-y divide-border/50 px-6">
          {transactions.length > 0 ? (
            transactions.slice(0, 5).map((tx) => {
              const isTransfer = tx.type === 'transfer';
              const isTransferIn = isTransfer && Boolean(selectedAccountId && tx.transfer_id === selectedAccountId);
              const isTransferOut = isTransfer && Boolean(selectedAccountId && tx.account_id === selectedAccountId);
              const isIncome = tx.type === 'income' || isTransferIn;
              const isExpense = tx.type === 'expense' || isTransferOut;
              const isTransferNeutral = isTransfer && !selectedAccountId;
              
              const category = categories.find(c => c.id === tx.category_id);
              const categoryName = category
                ? (CATEGORY_LABELS[category.name] || category.name)
                : t("dashboard.recent_transactions.no_category");
              const categoryIcon = category?.icon;
              const categoryColor = category?.color || "#9ca3af";

              const typeLabels: Record<string, string> = {
                income: t("dashboard.recent_transactions.type_income"),
                expense: t("dashboard.recent_transactions.type_expense"),
                transfer: t("dashboard.recent_transactions.type_transfer"),
              };
              const typeLabel = typeLabels[tx.type ?? "expense"] || t("dashboard.recent_transactions.type_expense");

              const relativeDate = formatRelativeDate(tx.date);
              
              // Sprawdzamy kto dodał transakcję
              // Jeśli uploaded_by jest null/undefined, traktujemy jako własną (np. stara transakcja bez usera)
              const isMine = !tx.uploaded_by || tx.uploaded_by === user?.id;
              const uploaderText = isMine ? t("dashboard.recent_transactions.added_by_me") : t("dashboard.recent_transactions.added_by_shared");

              return (
                <div key={tx.id} className="flex items-start justify-between gap-3 py-4 first:pt-2 last:pb-2 transition-colors">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    {/* Icon Circle */}
                    <div 
                      className={cn(
                        "size-12 rounded-full flex items-center justify-center shrink-0 shadow-inner",
                        isIncome ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                        isExpense && categoryIcon ? "" :
                        isExpense ? "bg-orange-100 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400" :
                        "bg-muted text-muted-foreground"
                      )}
                      style={isExpense && categoryIcon ? { backgroundColor: `${categoryColor}15` } : undefined}
                    >
                      {categoryIcon ? <CategoryIcon name={categoryIcon} className="size-5" style={{ color: categoryColor }} /> : (isIncome ? <ArrowUpRight className="size-6" /> :
                       isExpense ? <Store className="size-6" /> :
                       <ArrowDownRight className="size-6" />)}
                    </div>

                    {/* Details */}
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="text-sm md:text-base font-bold truncate leading-tight">
                        {tx.merchant_name}
                      </span>
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 mt-1 text-xs text-muted-foreground font-medium">
                        <span>{typeLabel}</span>
                        <span aria-hidden>•</span>
                        <span>{categoryName}</span>
                        <span aria-hidden>•</span>
                        <span>{relativeDate}</span>
                        <span aria-hidden>•</span>
                        <span className="opacity-70">{t("dashboard.recent_transactions.added_by_prefix")} {uploaderText}</span>
                      </div>

                      {tx.receipt_scan?.status === "processing" && (
                        <div className="mt-1">
                          <Badge variant="outline" className="h-4 px-1.5 text-[9px] animate-pulse uppercase border-amber-500 text-amber-500">{t("transactions.ai_processing")}</Badge>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Amount */}
                  <div className="text-right flex flex-col items-end shrink-0">
                    <span className={cn(
                      "text-sm md:text-base font-black tabular-nums whitespace-nowrap",
                      isTransferNeutral ? "text-blue-600 dark:text-blue-400" :
                      isIncome ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"
                    )}>
                      {isIncome ? "+" : isTransferNeutral ? "" : "-"}{(tx.total_amount ?? 0).toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                    <span className="text-[10px] text-muted-foreground font-bold tracking-tight">
                      {tx.currency ?? "PLN"}
                    </span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm">
              <p>{t("dashboard.recent_transactions.no_transactions")}</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
