import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";
import { CATEGORY_HEX_COLORS, CATEGORY_LABELS } from "@/lib/constants";

export function SpendingChart() {
  // Fetch real data
  const { data: receipts, isLoading } = useQuery({
    queryKey: ["receipts"],
    queryFn: api.getReceipts,
  });

  if (isLoading) {
    return (
      <Card className="rounded-2xl border-0 shadow-sm h-[400px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  // Aggregate Data
  const categoryTotals: Record<string, number> = {};
  
  receipts?.forEach((receipt) => {
    // Agregujemy wydatki na podstawie pozycji na paragonie
    if (receipt.items && receipt.items.length > 0) {
        receipt.items.forEach((item) => {
            const category = item.category || "Other";
            // Zakładamy, że item.price to całkowity koszt pozycji (lub cena * ilość)
            // Jeśli twoja logika biznesowa traktuje price jako jednostkową, dodaj * item.quantity
            const amount = item.price; 
            if (amount > 0) {
                categoryTotals[category] = (categoryTotals[category] || 0) + amount;
            }
        });
    } else if (receipt.total_amount > 0) {
        // Fallback: Jeśli brak pozycji, ale jest kwota całkowita, wrzuć do Inne (lub głównej kategorii jeśli by była)
        categoryTotals["Other"] = (categoryTotals["Other"] || 0) + receipt.total_amount;
    }
  });

  // Convert to array and sort
  const chartData = Object.entries(categoryTotals)
    .map(([key, value]) => ({ 
        name: CATEGORY_LABELS[key] || key, // Display Name (Polish)
        key: key, // Original key for color mapping
        value 
    }))
    .sort((a, b) => b.value - a.value);

  const total = chartData.reduce((sum, item) => sum + item.value, 0);

  return (
    <Card className="rounded-2xl border-0 shadow-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold">
              Wydatki wg Kategorii
            </CardTitle>
            <span className="text-sm font-bold text-primary bg-primary/10 px-3 py-1 rounded-full">
                Suma: {total.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
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
                    <Tooltip 
                        formatter={(value: number) => value.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
                        cursor={{ fill: 'rgba(0,0,0,0.05)', radius: 4 }}
                        contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                    />
                    <Bar 
                        dataKey="value" 
                        radius={[0, 6, 6, 0]} 
                        barSize={24}
                        animationDuration={1500}
                        animationEasing="ease-out"
                    >
                        {chartData.map((entry, index) => {
                            // Try to match color, handling case sensitivity robustly
                            let color = CATEGORY_HEX_COLORS[entry.key];
                            if (!color && entry.key) {
                                // Try capitalized (e.g. "food" -> "Food")
                                const capitalized = entry.key.charAt(0).toUpperCase() + entry.key.slice(1).toLowerCase();
                                color = CATEGORY_HEX_COLORS[capitalized];
                            }
                            return <Cell key={`cell-${index}`} fill={color || CATEGORY_HEX_COLORS["Other"]} />;
                        })}
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