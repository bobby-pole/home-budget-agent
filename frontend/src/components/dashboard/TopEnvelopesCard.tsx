import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface EnvelopeData {
  id: number;
  name: string;
  spent: number;
  limit: number;
  color: string;
}

interface TopEnvelopesCardProps {
  envelopes: EnvelopeData[];
  isLoading: boolean;
}

export function TopEnvelopesCard({ envelopes, isLoading }: TopEnvelopesCardProps) {
  if (isLoading) {
    return (
      <Card className="rounded-3xl border border-border/50 shadow-sm h-full bg-card animate-pulse" />
    );
  }

  return (
    <Card className="rounded-3xl border border-border/50 shadow-sm bg-card overflow-hidden h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-bold">Top Koperty</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6 mt-4">
        {envelopes.length > 0 ? (
          envelopes.map((env) => {
            const percentage = Math.min(Math.round((env.spent / env.limit) * 100), 100);
            const isNearLimit = percentage >= 80 && percentage < 100;
            const isOverLimit = percentage >= 100;

            return (
              <div key={env.id} className="space-y-2">
                <div className="flex justify-between items-end">
                  <div className="flex items-center gap-2">
                    <div className="size-2 rounded-full" style={{ backgroundColor: env.color }} />
                    <span className="text-sm font-bold truncate max-w-[120px]">{env.name}</span>
                  </div>
                  <span className="text-[10px] font-black text-muted-foreground uppercase">
                    {env.spent.toLocaleString("pl-PL")} / {env.limit.toLocaleString("pl-PL")} PLN
                  </span>
                </div>
                <div className="relative pt-1">
                  <Progress 
                    value={percentage} 
                    className={cn(
                      "h-2",
                      isOverLimit ? "bg-destructive/20" : "bg-muted"
                    )}
                  />
                  <div 
                    className={cn(
                      "absolute top-0 bottom-0 left-0 transition-all rounded-full",
                      isOverLimit ? "bg-destructive" : isNearLimit ? "bg-orange-500" : ""
                    )}
                    style={{ 
                      width: `${percentage}%`,
                      backgroundColor: !isOverLimit && !isNearLimit ? env.color : undefined 
                    }}
                  />
                </div>
                <div className="flex justify-between">
                  <span className={cn(
                    "text-[10px] font-bold",
                    isOverLimit ? "text-destructive" : isNearLimit ? "text-orange-500" : "text-muted-foreground"
                  )}>
                    {percentage}% wykorzystano
                  </span>
                  {isOverLimit && (
                    <span className="text-[10px] font-black text-destructive uppercase tracking-tighter">
                      Przekroczono!
                    </span>
                  )}
                </div>
              </div>
            );
          })
        ) : (
          <div className="flex flex-col items-center justify-center text-center py-12 space-y-2">
            <p className="text-sm text-muted-foreground">Brak ustawionych limitów.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
