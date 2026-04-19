import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PiggyBank, Zap, ArrowRight, TrendingUp } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface BudgetSummaryCardProps {
  remaining: number;
  planned: number;
  spent: number;
  income: number;
  onAddTransaction: () => void;
}

export function BudgetSummaryCard({
  remaining,
  planned,
  spent,
  income,
  onAddTransaction,
}: BudgetSummaryCardProps) {
  const isOverBudget = remaining < 0;

  if (planned === 0 && spent === 0 && income === 0) {
    return (
      <Card className="rounded-[32px] border border-dashed border-border p-8 bg-muted/30">
        <div className="flex flex-col items-center justify-center text-center space-y-4">
          <div className="size-12 rounded-2xl bg-primary/10 flex items-center justify-center">
            <PiggyBank className="size-6 text-primary" />
          </div>
          <div>
            <h3 className="text-lg font-semibold">Brak transakcji w tym miesiącu</h3>
            <p className="text-sm text-muted-foreground max-w-xs mx-auto">
              Dodaj swój pierwszy przychód lub wydatek, aby zacząć śledzić finanse.
            </p>
          </div>
          <Button onClick={onAddTransaction} className="rounded-full">
            Dodaj transakcję <ArrowRight className="ml-2 size-4" />
          </Button>
        </div>
      </Card>
    );
  }

  // Calculate progress for BudgetStatusSummary (spent vs income)
  // If income is 0, progress is 0% to avoid confusion.
  const progressPercentage = income > 0 ? Math.min(Math.round((spent / income) * 100), 100) : 0;

  return (
    <Card className="rounded-[32px] border-border/50 shadow-sm overflow-hidden bg-gradient-to-br from-indigo-50/80 via-white to-blue-50/50 dark:from-indigo-950/30 dark:via-background dark:to-blue-900/20">
      <CardContent className="p-6 md:p-8 flex flex-col gap-6">
        
        {/* Top Header: Badge & Trend */}
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/10 text-primary font-bold text-xs tracking-wider uppercase">
            <Zap className="size-3.5 fill-current" />
            Do wydania
          </div>
          {/* Opcjonalny wskaźnik trendu (mock) */}
          <div className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-bold text-xs">
            <TrendingUp className="size-3.5" />
            +0.0%
          </div>
        </div>

        {/* Main Amount */}
        <div>
          <h2 className={cn(
            "text-4xl md:text-5xl font-black tracking-tighter",
            isOverBudget ? "text-destructive" : "text-primary"
          )}>
            {remaining.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
          </h2>
          <p className="text-sm md:text-base font-medium text-muted-foreground mt-1">
            Dostępne w tym miesiącu
          </p>
        </div>

        {/* Progress Bar (BudgetStatusSummary) */}
        <div className="space-y-2 mt-2">
          <div className="flex justify-between text-xs font-bold text-muted-foreground">
            <span>Wykorzystanie przychodów ({progressPercentage}%)</span>
          </div>
          <Progress 
            value={progressPercentage} 
            className="h-2.5 bg-primary/10" 
            indicatorClassName={cn(
              progressPercentage >= 100 ? "bg-destructive animate-pulse" : "bg-primary"
            )}
          />
        </div>

        {/* Bottom Cards: Income & Spent */}
        <div className="grid grid-cols-2 gap-4 mt-2">
          <div className="bg-background/80 backdrop-blur-sm rounded-2xl p-4 md:p-5 border border-border/50 shadow-sm">
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Przychody
            </span>
            <div className="mt-1 font-black text-xl md:text-2xl text-emerald-600 dark:text-emerald-400 tracking-tighter">
              {income.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
            </div>
          </div>
          
          <div className="bg-background/80 backdrop-blur-sm rounded-2xl p-4 md:p-5 border border-border/50 shadow-sm">
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Wydano
            </span>
            <div className="mt-1 font-black text-xl md:text-2xl text-destructive tracking-tighter">
              {spent.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
            </div>
          </div>
        </div>

      </CardContent>
    </Card>
  );
}
