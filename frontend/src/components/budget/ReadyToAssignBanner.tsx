import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { getIntlLocale } from "@/lib/dates";

interface ReadyToAssignBannerProps {
  totalIncome: number;
  totalPlanned: number;
  onAddIncome: () => void;
}

export function ReadyToAssignBanner({ totalIncome, totalPlanned, onAddIncome }: ReadyToAssignBannerProps) {
  const readyToAssign = totalIncome - totalPlanned;
  const isNegative = readyToAssign < 0;
  
  return (
    <Card className={cn(
      "rounded-[32px] border-border/50 shadow-sm overflow-hidden",
      isNegative 
        ? "bg-gradient-to-br from-red-50/80 to-rose-100/50 dark:from-red-950/30 dark:to-rose-900/20" 
        : "bg-gradient-to-br from-emerald-50/80 via-white to-teal-50/50 dark:from-emerald-950/30 dark:via-background dark:to-teal-900/20"
    )}>
      <CardContent className="p-6 md:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex flex-col">
          <div className="flex items-center gap-2 mb-2">
            <div className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-full font-bold text-xs uppercase tracking-wider",
              isNegative ? "bg-destructive/10 text-destructive" : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            )}>
              <Sparkles className="size-3.5 fill-current" />
              {t("budget.ready_to_assign.badge")}
            </div>
          </div>
          
          <h2 className={cn(
            "text-4xl md:text-5xl font-black tracking-tighter",
            isNegative ? "text-destructive" : "text-emerald-600 dark:text-emerald-400"
          )}>
            {readyToAssign.toLocaleString(getIntlLocale(), { style: "currency", currency: "PLN" })}
          </h2>
          
          {isNegative ? (
            <p className="text-sm font-medium text-destructive mt-2">
              {t("budget.ready_to_assign.over_budget_message")}
            </p>
          ) : (
            <p className="text-sm font-medium text-muted-foreground mt-2">
              {readyToAssign > 0
                ? t("budget.ready_to_assign.assign_message")
                : t("budget.ready_to_assign.all_assigned_message")}
            </p>
          )}
        </div>
        
        <Button 
          onClick={onAddIncome}
          className={cn(
            "rounded-full font-bold shadow-lg h-12 px-6 transition-all active:scale-95 shrink-0",
            isNegative ? "shadow-destructive/20" : "shadow-emerald-500/20 bg-emerald-600 hover:bg-emerald-700 text-white"
          )}
        >
          <Plus className="mr-2 size-4" />
          {t("budget.ready_to_assign.add_income_button")}
        </Button>
      </CardContent>
    </Card>
  );
}
