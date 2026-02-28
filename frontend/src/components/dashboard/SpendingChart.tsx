import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/constants";

export function SpendingChart() {
  const { data: transactions, isLoading: isTransactionsLoading } = useQuery({
    queryKey: ["transactions"],
    queryFn: api.getTransactions,
  });

  const { data: categories, isLoading: isCategoriesLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  if (isTransactionsLoading || isCategoriesLoading) {
    return (
      <Card className="rounded-2xl border-0 shadow-sm h-[400px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  // Aggregate Data
  const categoryTotals: Record<string, { value: number; color: string; icon: string }> = {};

  const now = new Date();
  const curMonth = now.getMonth();
  const curYear = now.getFullYear();

  const getCategoryById = (categoryId: number | null) => {
    if (categoryId == null || !categories) return { name: "Inne", color: "#9ca3af", icon: "📦" };
    const cat = categories.find(c => c.id === categoryId);
    if (!cat) return { name: "Inne", color: "#9ca3af", icon: "📦" };
    const displayName = cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name;
    return { name: displayName, color: cat.color || "#9ca3af", icon: cat.icon || "📦" };
  };

  transactions?.forEach((transaction) => {
    const isDone = !transaction.receipt_scan || transaction.receipt_scan.status === "done";
    if (!isDone) return;
    if (!transaction.date) return;
    const rDate = new Date(transaction.date);
    if (rDate.getMonth() !== curMonth || rDate.getFullYear() !== curYear)
      return;

    transaction.lines.forEach((item) => {
      const displayCat = getCategoryById(item.category_id);

      if (item.price > 0) {
        if (!categoryTotals[displayCat.name]) {
          categoryTotals[displayCat.name] = { value: 0, color: displayCat.color, icon: displayCat.icon };
        }
        categoryTotals[displayCat.name].value += item.price;
      }
    });
  });

  // Convert to array and sort
  const chartData = Object.entries(categoryTotals)
    .map(([name, data]) => ({
      name,
      value: data.value,
      color: data.color,
      icon: data.icon
    }))
    .sort((a, b) => b.value - a.value);

  const total = chartData.reduce((sum, item) => sum + item.value, 0);

  return (
    <Card className="rounded-2xl border border-border/50 shadow-sm bg-card/50 backdrop-blur-sm overflow-hidden">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold">
            Wydatki wg Kategorii
          </CardTitle>
          <span className="text-sm font-bold text-primary bg-primary/10 px-3 py-1 rounded-full">
            Suma:{" "}
            {total.toLocaleString("pl-PL", {
              style: "currency",
              currency: "PLN",
            })}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] w-full mt-2">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 0, right: 20, left: 10, bottom: 0 }}
              >
                <XAxis type="number" hide />
                <YAxis
                  dataKey="name"
                  type="category"
                  width={90}
                  tick={{ fontSize: 13, fill: "#64748b", fontWeight: 500 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Bar
                  dataKey="value"
                  radius={[0, 6, 6, 0]}
                  barSize={24}
                  animationDuration={1500}
                  animationEasing="ease-out"
                >
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.color}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col h-full items-center justify-center text-muted-foreground text-sm">
              <p>Brak danych o wydatkach.</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
