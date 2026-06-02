import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { getIntlLocale } from "@/lib/dates";
import { CategoryIcon } from "@/components/CategoryIcon";

export interface EnvelopeItem {
  categoryId: number;
  categoryName: string;
  planned: number;
  spent: number;
  remaining: number;
  icon: string;
  color: string;
}

interface EnvelopeGroupListProps {
  items: EnvelopeItem[];
  isLoading: boolean;
  onEnvelopeClick: (env: EnvelopeItem) => void;
  year: number;
  month: number;
}

export function EnvelopeGroupList({ items, isLoading, onEnvelopeClick, year, month }: EnvelopeGroupListProps) {
  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <Card key={i} className="rounded-[32px] border-border/50 h-32 bg-card animate-pulse" />
        ))}
      </div>
    );
  }

  const now = new Date();
  const isCurrentMonth = now.getFullYear() === year && (now.getMonth() + 1) === month;
  const daysInMonth = new Date(year, month, 0).getDate();
  const daysLeft = isCurrentMonth ? (daysInMonth - now.getDate() + 1) : 0;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-bold px-2 pt-4">{t("budget.envelope_list.title")}</h3>

      {items.length === 0 ? (
        <Card className="rounded-[32px] border-border/50 bg-muted/30 p-8 text-center border-dashed">
          <p className="text-muted-foreground text-sm font-medium">{t("budget.envelope_list.no_categories")}</p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((env) => {
            const percentage = env.planned > 0 ? Math.min(Math.round((env.spent / env.planned) * 100), 100) : (env.spent > 0 ? 100 : 0);
            const isOverLimit = env.remaining < 0;
            const remainingSafe = env.remaining > 0 ? env.remaining : 0;
            
            // Pacing
            let pacingText = "";
            let isPacingSafe = false;
            if (isCurrentMonth && daysLeft > 0 && remainingSafe > 0) {
              const daily = remainingSafe / daysLeft;
              pacingText = `${t("budget.envelope_list.pacing_safe_prefix")} ${daily.toLocaleString(getIntlLocale(), { maximumFractionDigits: 0 })} ${t("budget.envelope_list.pacing_safe_suffix")}`;
              isPacingSafe = true;
            } else if (isOverLimit) {
              pacingText = t("budget.envelope_list.pacing_over_limit");
            } else if (remainingSafe === 0 && env.planned > 0) {
              pacingText = t("budget.envelope_list.pacing_funds_exhausted");
            } else if (env.planned === 0) {
              pacingText = t("budget.envelope_list.pacing_no_plan");
            }

            return (
              <Card 
                key={env.categoryId} 
                className={cn(
                  "rounded-[32px] border-border/50 shadow-sm bg-card hover:bg-muted/30 transition-all cursor-pointer group",
                  isOverLimit && "border-destructive/30 bg-destructive/5 dark:bg-destructive/10 hover:bg-destructive/10 dark:hover:bg-destructive/15"
                )}
                onClick={() => onEnvelopeClick(env)}
                role="button"
                aria-label={`${t("budget.allocation_drawer.set_limit_subtitle")}: ${env.categoryName}. ${t("dashboard.top_envelopes.remaining_prefix")} ${env.remaining} ${t("common.currency")}.`}
              >                <CardContent className="p-4 sm:p-6">
                  <div className="flex flex-col gap-4">
                    {/* Header: Icon, Name, Pacing */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div 
                          className="size-10 rounded-full flex items-center justify-center shrink-0" 
                          style={{ backgroundColor: `${env.color || "#3b82f6"}15` }}
                        >
                          <CategoryIcon name={env.icon} className="size-5" style={{ color: env.color || "#3b82f6" }} />
                        </div>
                        <div className="flex flex-col">
                          <span className="text-base font-bold leading-tight flex items-center gap-1.5">
                            {env.categoryName}
                            {isOverLimit && <AlertTriangle className="h-4 w-4 text-destructive shrink-0 animate-bounce" style={{ animationDuration: '2s' }} />}
                          </span>
                          <span className={cn(
                            "text-[11px] font-bold uppercase tracking-tight mt-0.5",
                            isOverLimit ? "text-destructive" : (isPacingSafe ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")
                          )}>
                            {pacingText}
                          </span>
                        </div>
                      </div>
                    </div>
                    
                    {/* Progress Bar */}
                    <div className="w-full">
                      <div className="relative">
                        <Progress 
                          value={percentage} 
                          className={cn("h-1.5", isOverLimit ? "bg-destructive/20" : "bg-muted")}
                          indicatorClassName={cn(isOverLimit ? "bg-destructive animate-pulse" : "bg-[var(--indicator-color)]")}
                          style={{ "--indicator-color": !isOverLimit ? env.color : undefined } as React.CSSProperties}
                        />
                      </div>
                    </div>

                    {/* Columns: Planned, Spent, Remaining */}
                    <div className="grid grid-cols-3 gap-2 text-center divide-x divide-border/50 pt-2">
                      <div className="flex flex-col">
                        <span className="text-[9px] uppercase font-bold text-muted-foreground mb-0.5">{t("budget.envelope_list.col_planned")}</span>
                        <span className="text-xs font-black tabular-nums text-foreground">
                          {env.planned.toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[9px] uppercase font-bold text-muted-foreground mb-0.5">{t("budget.envelope_list.col_spent")}</span>
                        <span className="text-xs font-black tabular-nums text-foreground">
                          {env.spent.toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[9px] uppercase font-bold text-muted-foreground mb-0.5">{t("budget.envelope_list.col_remaining")}</span>
                        <span className={cn(
                          "text-xs font-black tabular-nums",
                          isOverLimit ? "text-destructive" : "text-primary"
                        )}>
                          {env.remaining.toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })}
                        </span>
                      </div>
                    </div>

                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
