import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Store, ArrowRight, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { TransactionRead } from "@/client";
import { cn } from "@/lib/utils";

interface RecentTransactionsListProps {
  transactions: TransactionRead[];
  isLoading: boolean;
}

export function RecentTransactionsList({ transactions, isLoading }: RecentTransactionsListProps) {
  if (isLoading) {
    return (
      <Card className="rounded-3xl border border-border/50 shadow-sm h-[400px] bg-card animate-pulse" />
    );
  }

  return (
    <Card className="rounded-3xl border border-border/50 shadow-sm bg-card overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-bold">Ostatnie Transakcje</CardTitle>
        <Button variant="ghost" size="sm" asChild className="text-primary font-bold rounded-full">
          <Link to="/transactions">
            Wszystkie <ArrowRight className="ml-1 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="px-0">
        <div className="divide-y divide-border/50">
          {transactions.length > 0 ? (
            transactions.slice(0, 5).map((tx) => {
              const isIncome = tx.type === 'income';
              const isExpense = tx.type === 'expense';
              
              return (
                <div key={tx.id} className="flex items-center justify-between p-4 hover:bg-muted/30 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "size-10 rounded-2xl flex items-center justify-center shrink-0",
                      isIncome ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                      isExpense ? "bg-orange-100 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400" :
                      "bg-muted text-muted-foreground"
                    )}>
                      {isIncome ? <ArrowUpRight className="size-5" /> : 
                       isExpense ? <ArrowDownRight className="size-5" /> :
                       <Store className="size-5" />}
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="text-sm font-bold truncate leading-tight">
                        {tx.merchant_name}
                      </span>
                      {tx.note && (
                        <span className="text-[10px] text-muted-foreground truncate italic leading-tight">
                          {tx.note}
                        </span>
                      )}
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-muted-foreground font-medium">
                          {tx.date ? new Date(tx.date).toLocaleDateString("pl-PL") : "Brak daty"}
                        </span>
                        {tx.receipt_scan?.status === "processing" && (
                          <Badge variant="outline" className="h-3.5 px-1 text-[8px] animate-pulse uppercase">AI Processing</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="text-right flex flex-col items-end">
                    <span className={cn(
                      "text-sm font-black tabular-nums",
                      isIncome ? "text-emerald-600 dark:text-emerald-400" : "text-foreground"
                    )}>
                      {isIncome ? "+" : "-"}{(tx.total_amount ?? 0).toLocaleString("pl-PL", { minimumFractionDigits: 2 })} {tx.currency ?? "PLN"}
                    </span>
                    <span className="text-[9px] text-muted-foreground font-bold uppercase tracking-tighter">
                      {tx.type}
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
