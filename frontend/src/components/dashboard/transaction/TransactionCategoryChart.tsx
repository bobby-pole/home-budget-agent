import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import type { TransactionLineRead as TransactionLine } from "@/client";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { CATEGORY_LABELS } from "@/lib/constants";

interface TransactionCategoryChartProps {
  lines: TransactionLine[];
  currency: string;
}

const COLORS = [
  "#3b82f6", // blue-500
  "#10b981", // emerald-500
  "#f59e0b", // amber-500
  "#ef4444", // red-500
  "#8b5cf6", // violet-500
  "#ec4899", // pink-500
  "#06b6d4", // cyan-500
  "#14b8a6", // teal-500
  "#f97316", // orange-500
  "#64748b", // slate-500
];

export function TransactionCategoryChart({ lines, currency }: TransactionCategoryChartProps) {
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const chartData = useMemo(() => {
    if (!lines || lines.length === 0) return [];

    const grouped = lines.reduce((acc, line) => {
      // Ignore adjustments like discounts from the pie chart unless we want to show them?
      // Actually, if it's an adjustment, it might just reduce the total.
      // We'll map by category_id.
      if (line.is_adjustment) return acc;

      const catId = line.category_id || 0; // 0 for Uncategorized
      const total = line.price * (line.quantity || 1);

      if (!acc[catId]) {
        acc[catId] = 0;
      }
      acc[catId] += total;
      return acc;
    }, {} as Record<number, number>);

    // Create array for Recharts
    const data = Object.entries(grouped).map(([idStr, total]) => {
      const catId = parseInt(idStr, 10);
      let name = t("transactions.detail_modal.chart.uncategorized"); // Fallback
      if (catId !== 0 && categories) {
        const catObj = categories.find((c) => c.id === catId);
        if (catObj) {
          name = CATEGORY_LABELS[catObj.name] || catObj.name;
        }
      }
      return {
        name,
        value: total > 0 ? parseFloat(total.toFixed(2)) : 0, // Avoid negative segments in pie chart
      };
    }).filter(item => item.value > 0); // Recharts Pie cannot handle negative values well

    return data.sort((a, b) => b.value - a.value);
  }, [lines, categories]);

  if (!lines || lines.length === 0) return null;
  if (chartData.length === 0) return null;

  return (
    <Accordion type="single" collapsible className="w-full bg-card border rounded-md">
      <AccordionItem value="chart" className="border-b-0">
        <AccordionTrigger className="px-4 py-3 hover:no-underline hover:bg-muted/50 rounded-md transition-colors text-sm font-medium">
          {t("transactions.detail_modal.chart.title")}
        </AccordionTrigger>
        <AccordionContent className="px-4 pb-4 pt-2 border-t">
          <div className="h-[250px] w-full mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                  animationDuration={800}
                >
                  {chartData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  formatter={(value: unknown) => [`${Number(value).toFixed(2)} ${currency}`, t("transactions.detail_modal.chart.tooltip_amount")]}
                  contentStyle={{ borderRadius: '8px', border: '1px solid var(--border)' }}
                />
                <Legend 
                  verticalAlign="bottom" 
                  height={36} 
                  iconType="circle"
                  formatter={(value) => <span className="text-sm font-medium text-foreground">{value}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
