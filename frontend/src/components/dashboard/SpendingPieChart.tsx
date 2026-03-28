import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { Loader2 } from "lucide-react";

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
      <Card className="rounded-3xl border border-border/50 shadow-sm h-[400px] flex items-center justify-center bg-card">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  return (
    <Card className="rounded-3xl border border-border/50 shadow-sm bg-card overflow-hidden flex flex-col h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-bold">Wydatki wg Kategorii</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col">
        <div className="flex-1 min-h-[250px] w-full relative">
          {data.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                    animationDuration={1000}
                  >
                    {data.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                    // @ts-expect-error - Recharts types are incompatible with strictNullChecks here
                    formatter={(value: number) => value?.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-xs text-muted-foreground font-medium">Suma</span>
                <span className="text-xl font-black">
                  {total.toLocaleString("pl-PL", {
                    maximumFractionDigits: 0,
                  })}
                </span>
              </div>
            </>
          ) : (
            <div className="flex flex-col h-full items-center justify-center text-muted-foreground text-sm py-12">
              <p>Brak danych o wydatkach.</p>
            </div>
          )}
        </div>

        {/* Legend */}
        {data.length > 0 && (
          <div className="grid grid-cols-2 gap-2 mt-4">
            {data.slice(0, 4).map((item, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
                <span className="text-xs font-medium truncate">{item.name}</span>
              </div>
            ))}
            {data.length > 4 && (
              <div className="flex items-center gap-2">
                <div className="size-2 rounded-full bg-muted" />
                <span className="text-xs font-medium text-muted-foreground">+{data.length - 4} więcej</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
