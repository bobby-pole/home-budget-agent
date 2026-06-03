import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { t } from "@/lib/i18n";
import { getIntlLocale } from "@/lib/dates";

interface SpendingPieChartProps {
  data: Array<{
    name: string;
    value: number;
    color: string;
  }>;
  isLoading: boolean;
}

export function SpendingPieChart({ data, isLoading }: SpendingPieChartProps) {
  const [excludedCategories, setExcludedCategories] = useState<Set<string>>(new Set());

  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm h-[400px] flex items-center justify-center bg-card">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  // Filter out excluded categories
  const filteredData = data.filter(item => !excludedCategories.has(item.name));

  // Calculate new total based on active categories
  const activeTotal = filteredData.reduce((sum, item) => sum + item.value, 0);

  // Pre-calculate base values for legend and sorting
  const sortedChartData = filteredData.map(item => ({
    ...item,
    percentage: 0 // Will be calculated after grouping
  })).sort((a, b) => b.value - a.value);

  const displayedData = sortedChartData.slice(0, 5);
  const otherData = sortedChartData.slice(5);
  if (otherData.length > 0) {
    const otherValue = otherData.reduce((sum, item) => sum + item.value, 0);
    displayedData.push({
      name: t("dashboard.spending_pie.other_category"),
      value: otherValue,
      color: "#9ca3af",
      percentage: 0
    });
  }

  // Normalize percentages using Largest Remainder Method to ensure they sum up to exactly 100%
  if (activeTotal > 0 && displayedData.length > 0) {
    const itemsWithParts = displayedData.map((item, idx) => {
      const precise = (item.value / activeTotal) * 100;
      const integer = Math.floor(precise);
      const fraction = precise - integer;
      return {
        idx,
        integer,
        fraction,
      };
    });

    const integerSum = itemsWithParts.reduce((sum, item) => sum + item.integer, 0);
    const diff = 100 - integerSum;

    // Sort index references by fractional part descending
    const sortedByFraction = [...itemsWithParts].sort((a, b) => b.fraction - a.fraction);

    // Distribute the remainder
    for (let i = 0; i < diff; i++) {
      const itemToIncrement = sortedByFraction[i % sortedByFraction.length];
      const target = itemsWithParts.find(it => it.idx === itemToIncrement.idx);
      if (target) {
        target.integer += 1;
      }
    }

    // Assign normalized percentages back
    itemsWithParts.forEach(item => {
      displayedData[item.idx].percentage = item.integer;
    });
  }

  const handleToggleCategory = (categoryName: string) => {
    setExcludedCategories(prev => {
      const next = new Set(prev);
      if (next.has(categoryName)) {
        next.delete(categoryName);
      } else {
        if (categoryName === t("dashboard.spending_pie.other_category")) {
          // Exclude all currently grouped "other" categories
          otherData.forEach(item => next.add(item.name));
        } else {
          next.add(categoryName);
        }
      }
      return next;
    });
  };

  const handleRestoreAll = () => {
    setExcludedCategories(new Set());
  };

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden flex flex-col h-full">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="text-lg font-bold">{t("dashboard.spending_pie.title")}</CardTitle>
          <p className="text-xs text-muted-foreground font-medium">{t("dashboard.spending_pie.subtitle")}</p>
        </div>
        <Link to="/budget">
          <Button variant="ghost" size="sm" className="bg-primary/5 text-primary font-bold rounded-full px-4">
            {t("dashboard.spending_pie.details_button")}
          </Button>
        </Link>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col justify-between pt-4">
        <div className="flex flex-row items-center justify-between w-full gap-4 flex-1">
          {/* Chart Left */}
          <div className="relative size-[180px] shrink-0">
            {data.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={displayedData}
                      cx="50%"
                      cy="50%"
                      innerRadius={65}
                      outerRadius={85}
                      paddingAngle={4}
                      dataKey="value"
                      animationDuration={400}
                      onClick={(entry) => {
                        if (entry && entry.name) {
                          handleToggleCategory(entry.name);
                        }
                      }}
                    >
                      {displayedData.map((entry, index) => (
                        <Cell 
                          key={`cell-${index}`} 
                          fill={entry.color} 
                          stroke="none" 
                          style={{ cursor: "pointer", outline: "none" }}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                      formatter={(value) => value ? Number(value).toLocaleString(getIntlLocale(), { style: "currency", currency: "PLN" }) : ""}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-xl font-black tracking-tighter">
                    {activeTotal.toLocaleString(getIntlLocale(), {
                      maximumFractionDigits: 0,
                    })}
                  </span>
                  <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-widest">{t("dashboard.spending_pie.center_label")}</span>
                </div>
              </>
            ) : (
              <div className="flex flex-col h-full items-center justify-center text-muted-foreground text-[10px] py-12 text-center uppercase font-black">
                <p>{t("dashboard.spending_pie.no_data")}</p>
              </div>
            )}
          </div>

          {/* Legend Right */}
          <div className="flex-1 space-y-1.5 max-h-[180px] overflow-y-auto pr-1">
            {displayedData.map((item) => (
              <button
                key={item.name}
                onClick={() => handleToggleCategory(item.name)}
                className="flex items-center justify-between text-xs font-bold w-full text-left hover:bg-muted/50 p-1.5 rounded-xl transition-all cursor-pointer focus:outline-none focus:ring-1 focus:ring-primary/20 group"
                title={`${item.name}: ${item.value.toLocaleString(getIntlLocale(), { style: "currency", currency: "PLN" })}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <div className="size-2 rounded-full shrink-0 transition-transform group-hover:scale-125" style={{ backgroundColor: item.color }} />
                  <span className="truncate text-muted-foreground group-hover:text-foreground transition-colors">{item.name}</span>
                </div>
                <span className="text-foreground shrink-0 font-black">{item.percentage}%</span>
              </button>
            ))}
          </div>
        </div>

        {/* Excluded Categories Section */}
        {excludedCategories.size > 0 && (
          <div className="mt-4 pt-4 border-t border-border/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-widest">
                {t("dashboard.spending_pie.excluded_title")}
              </span>
              <button
                onClick={handleRestoreAll}
                className="text-[10px] text-primary hover:text-primary/80 font-bold transition-colors focus:outline-none cursor-pointer"
              >
                {t("dashboard.spending_pie.restore_all")}
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5 max-h-[80px] overflow-y-auto pr-1">
              {Array.from(excludedCategories).map(catName => {
                const origItem = data.find(d => d.name === catName);
                const color = origItem?.color || "#9ca3af";
                return (
                  <button
                    key={catName}
                    onClick={() => handleToggleCategory(catName)}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-muted/60 hover:bg-muted text-[11px] font-bold border border-border/50 transition-all cursor-pointer focus:outline-none group"
                  >
                    <div className="size-1.5 rounded-full opacity-60" style={{ backgroundColor: color }} />
                    <span className="line-through text-muted-foreground group-hover:no-underline transition-all">{catName}</span>
                    <span className="text-muted-foreground/50 group-hover:text-foreground text-[9px] font-bold transition-colors">+</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
