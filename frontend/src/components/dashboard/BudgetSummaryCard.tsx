import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PiggyBank, TrendingUp, TrendingDown, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface BudgetSummaryCardProps {
  remaining: number;
  planned: number;
  spent: number;
  income: number;
  onSetUpBudget: () => void;
}

export function BudgetSummaryCard({
  remaining,
  planned,
  spent,
  income,
  onSetUpBudget,
}: BudgetSummaryCardProps) {
  const isOverBudget = remaining < 0;

  if (planned === 0 && spent === 0) {
    return (
      <Card className="rounded-3xl border border-dashed border-border p-8 bg-muted/30">
        <div className="flex flex-col items-center justify-center text-center space-y-4">
          <div className="size-12 rounded-2xl bg-primary/10 flex items-center justify-center">
            <PiggyBank className="size-6 text-primary" />
          </div>
          <div>
            <h3 className="text-lg font-semibold">Nie masz jeszcze budżetu</h3>
            <p className="text-sm text-muted-foreground max-w-xs mx-auto">
              Zaplanuj swoje wydatki, aby lepiej kontrolować swoje finanse.
            </p>
          </div>
          <Button onClick={onSetUpBudget} className="rounded-full">
            Skonfiguruj budżet <ArrowRight className="ml-2 size-4" />
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className="rounded-3xl border-border/50 shadow-sm overflow-hidden bg-card">
      <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-border">
        {/* Remaining */}
        <div className="p-6 flex flex-col justify-between">
          <div>
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Pozostało
            </span>
            <div className="mt-1 flex items-baseline gap-2">
              <h2 className={cn(
                "text-3xl font-black tracking-tighter",
                isOverBudget ? "text-destructive" : "text-foreground"
              )}>
                {remaining.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
              </h2>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            z {planned.toLocaleString("pl-PL")} PLN zaplanowanych
          </p>
        </div>

        {/* Income */}
        <div className="p-6 flex flex-col justify-between">
          <div>
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Przychody
            </span>
            <div className="mt-1 flex items-center gap-2">
              <h2 className="text-3xl font-black tracking-tighter text-emerald-600 dark:text-emerald-500">
                {income.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
              </h2>
              <div className="size-6 rounded-full bg-emerald-100 dark:bg-emerald-500/10 flex items-center justify-center">
                <TrendingUp className="size-3.5 text-emerald-600 dark:text-emerald-400" />
              </div>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2 italic">
            W tym miesiącu
          </p>
        </div>

        {/* Spent */}
        <div className="p-6 flex flex-col justify-between">
          <div>
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Wydano
            </span>
            <div className="mt-1 flex items-center gap-2">
              <h2 className="text-3xl font-black tracking-tighter text-foreground">
                {spent.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
              </h2>
              <div className="size-6 rounded-full bg-orange-100 dark:bg-orange-500/10 flex items-center justify-center">
                <TrendingDown className="size-3.5 text-orange-600 dark:text-orange-400" />
              </div>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2 italic">
            Suma wszystkich wydatków
          </p>
        </div>
      </div>
    </Card>
  );
}
