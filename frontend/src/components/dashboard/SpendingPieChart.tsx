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

interface SpendingPieChartProps {
  data: Array<{
    name: string;
    value: number;
    color: string;
  }>;
  isLoading: boolean;
  total: number;
}

export function SpendingPieChart({ data, isLoading, total }: SpendingPieChartProps) {
  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm h-[400px] flex items-center justify-center bg-card">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  // Pre-calculate percentages for legend
  const chartData = data.map(item => ({
    ...item,
    percentage: total > 0 ? Math.round((item.value / total) * 100) : 0
  })).sort((a, b) => b.value - a.value);

  const displayedData = chartData.slice(0, 5);
  const otherData = chartData.slice(5);
  if (otherData.length > 0) {
    const otherValue = otherData.reduce((sum, item) => sum + item.value, 0);
    displayedData.push({
      name: "Inne",
      value: otherValue,
      color: "#9ca3af",
      percentage: Math.round((otherValue / total) * 100)
    });
  }

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden flex flex-col h-full">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="text-lg font-bold">Wydatki miesięczne</CardTitle>
          <p className="text-xs text-muted-foreground font-medium">Bieżący okres</p>
        </div>
        <Link to="/budget">
          <Button variant="ghost" size="sm" className="bg-primary/5 text-primary font-bold rounded-full px-4">
            Szczegóły
          </Button>
        </Link>
      </CardHeader>
      <CardContent className="flex-1 flex items-center pt-4">
        <div className="flex flex-row items-center justify-between w-full gap-4">
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
                      animationDuration={1000}
                    >
                      {displayedData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                      formatter={(value: number | string | undefined) => value ? Number(value).toLocaleString("pl-PL", { style: "currency", currency: "PLN" }) : ""}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-xl font-black tracking-tighter">
                    {total.toLocaleString("pl-PL", {
                      maximumFractionDigits: 0,
                    })}
                  </span>
                  <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-widest">Suma</span>
                </div>
              </>
            ) : (
              <div className="flex flex-col h-full items-center justify-center text-muted-foreground text-[10px] py-12 text-center uppercase font-black">
                <p>Brak danych</p>
              </div>
            )}
          </div>

          {/* Legend Right */}
          <div className="flex-1 space-y-2">
            {displayedData.map((item, i) => (
              <div key={i} className="flex items-center justify-between text-xs font-bold">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="size-2 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
                  <span className="truncate text-muted-foreground">{item.name}</span>
                </div>
                <span className="text-foreground shrink-0">{item.percentage}%</span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
