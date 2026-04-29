import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { format } from "date-fns";
import { pl } from "date-fns/locale";
import { AlertCircle, CheckCircle2, Clock } from "lucide-react";
import type { TransactionRead as Transaction } from "@/client";

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
        <h3 className="text-lg font-medium text-muted-foreground">Wszystko sprawdzone!</h3>
        <p className="text-sm text-muted-foreground/60 max-w-[200px]">
          Nie masz obecnie żadnych transakcji oczekujących na weryfikację.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {transactions.map((t) => {
        const isSelected = selectedId === t.id;
        const status = t.receipt_scan?.status || "processing";
        
        return (
          <Card
            key={t.id}
            className={cn(
              "cursor-pointer transition-all duration-200 hover:border-primary/50 hover:shadow-md border-border/50",
              isSelected ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "bg-card/50"
            )}
            onClick={() => onSelect(t)}
          >
            <CardContent className="p-4">
              <div className="flex justify-between items-start gap-2">
                <div className="min-w-0">
                  <h4 className="font-semibold text-sm truncate">
                    {t.merchant_name || "Przetwarzanie..."}
                  </h4>
                  <p className="text-xs text-muted-foreground mt-1">
                    {t.date ? format(new Date(t.date), "PPP", { locale: pl }) : "Brak daty"}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-bold">
                    {(t.total_amount ?? 0).toFixed(2)} {t.currency}
                  </div>
                  <div className="mt-2 flex justify-end">
                    {status === "processing" && (
                      <Badge variant="secondary" className="text-[10px] h-5 bg-blue-500/10 text-blue-500 border-blue-500/20 gap-1">
                        <Clock className="h-3 w-3 animate-pulse" />
                        AI...
                      </Badge>
                    )}
                    {status === "needs_review" && (
                      <Badge variant="outline" className="text-[10px] h-5 bg-amber-500/10 text-amber-500 border-amber-500/20 gap-1">
                        <AlertCircle className="h-3 w-3" />
                        Weryfikacja
                      </Badge>
                    )}
                    {status === "error" && (
                      <Badge variant="destructive" className="text-[10px] h-5 gap-1">
                        <AlertCircle className="h-3 w-3" />
                        Błąd
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
