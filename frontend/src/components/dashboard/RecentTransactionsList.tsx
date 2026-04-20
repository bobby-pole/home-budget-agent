import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Store, ArrowRight, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { TransactionRead, CategoryRead } from "@/client";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";
import { CATEGORY_LABELS } from "@/lib/constants";

interface RecentTransactionsListProps {
  transactions: TransactionRead[];
  categories?: CategoryRead[];
  isLoading: boolean;
}

function formatRelativeDate(dateString: string | null | undefined): string {
  if (!dateString) return "Brak daty";
  
  const date = new Date(dateString);
  const now = new Date();
  
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();

  if (isToday) return "Dzisiaj";
  if (isYesterday) return "Wczoraj";
  
  return date.toLocaleDateString("pl-PL", { day: "numeric", month: "short" });
}

export function RecentTransactionsList({ transactions, categories = [], isLoading }: RecentTransactionsListProps) {
  const { user } = useAuth();

  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm h-[400px] bg-card animate-pulse" />
    );
  }

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-bold">Ostatnia aktywność</CardTitle>
        <Button variant="ghost" size="sm" asChild className="text-primary font-bold rounded-full">
          <Link to="/transactions">
            Wszystkie <ArrowRight className="ml-1 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="px-0">
        <div className="divide-y divide-border/50 px-6">
          {transactions.length > 0 ? (
            transactions.slice(0, 5).map((tx) => {
              const isIncome = tx.type === 'income';
              const isExpense = tx.type === 'expense';
              
              const category = categories.find(c => c.id === tx.category_id);
              const categoryName = category 
                ? (category.is_system ? (CATEGORY_LABELS[category.name] || category.name) : category.name)
                : "Brak kategorii";
              const categoryIcon = category?.icon;

              const typeLabels: Record<string, string> = {
                income: "Przychód",
                expense: "Wydatek",
                transfer: "Transfer"
              };
              const typeLabel = typeLabels[tx.type ?? "expense"] || "Wydatek";

              const relativeDate = formatRelativeDate(tx.date);
              
              // Sprawdzamy kto dodał transakcję
              // Jeśli uploaded_by jest null/undefined, traktujemy jako własną (np. stara transakcja bez usera)
              const isMine = !tx.uploaded_by || tx.uploaded_by === user?.id;
              const uploaderText = isMine ? "Ty" : "Współdzielone";

              return (
                <div key={tx.id} className="flex items-center justify-between py-4 first:pt-2 last:pb-2 transition-colors">
                  <div className="flex items-center gap-4">
                    {/* Icon Circle */}
                    <div className={cn(
                      "size-12 rounded-full flex items-center justify-center shrink-0 shadow-inner text-xl",
                      isIncome ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                      isExpense && categoryIcon ? "bg-muted" :
                      isExpense ? "bg-orange-100 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400" :
                      "bg-muted text-muted-foreground"
                    )}>
                      {categoryIcon ? categoryIcon : (isIncome ? <ArrowUpRight className="size-6" /> : 
                       isExpense ? <Store className="size-6" /> :
                       <ArrowDownRight className="size-6" />)}
                    </div>
                    
                    {/* Details */}
                    <div className="flex flex-col min-w-0">
                      <span className="text-sm md:text-base font-bold truncate leading-tight">
                        {tx.merchant_name}
                      </span>
                      <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground font-medium">
                        <span className="truncate">{typeLabel}</span>
                        <span>•</span>
                        <span className="truncate">{categoryName}</span>
                        <span>•</span>
                        <span>{relativeDate}</span>
                        <span>•</span>
                        <span className="truncate opacity-70">Dodał: {uploaderText}</span>
                      </div>
                      
                      {tx.receipt_scan?.status === "processing" && (
                        <div className="mt-1">
                          <Badge variant="outline" className="h-4 px-1.5 text-[9px] animate-pulse uppercase border-amber-500 text-amber-500">AI Processing</Badge>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  {/* Amount */}
                  <div className="text-right flex flex-col items-end">
                    <span className={cn(
                      "text-sm md:text-base font-black tabular-nums",
                      isIncome ? "text-emerald-600 dark:text-emerald-400" : 
                      tx.type === 'transfer' ? "text-blue-600 dark:text-blue-400" : "text-destructive"
                    )}>
                      {isIncome ? "+" : tx.type === 'transfer' ? "" : "-"}{(tx.total_amount ?? 0).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
              <p>Brak niedawnych transakcji.</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
