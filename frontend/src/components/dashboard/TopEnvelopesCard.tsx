import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

interface EnvelopeData {
  id: number;
  name: string;
  spent: number;
  limit: number;
  color: string;
  icon?: string;
}

interface TopEnvelopesCardProps {
  envelopes: EnvelopeData[];
  isLoading: boolean;
}

export function TopEnvelopesCard({ envelopes, isLoading }: TopEnvelopesCardProps) {
  if (isLoading) {
    return (
      <Card className="rounded-[32px] border border-border/50 shadow-sm h-full bg-card animate-pulse" />
    );
  }

  return (
    <Card className="rounded-[32px] border border-border/50 shadow-sm bg-card overflow-hidden h-full">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-bold">Najważniejsze koperty</CardTitle>
        <Button variant="ghost" size="sm" asChild className="text-primary font-bold rounded-full">
          <Link to="/budget">
            Wszystkie <ArrowRight className="ml-1 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="px-0">
        <div className="divide-y divide-border/50 px-6">
          {envelopes.length > 0 ? (
            envelopes.map((env) => {
              const percentage = Math.min(Math.round((env.spent / env.limit) * 100), 100);
              const isOverLimit = percentage >= 100;
              const remaining = env.limit - env.spent;

              return (
                <div key={env.id} className="py-4 space-y-3 first:pt-2 last:pb-2">
                  <div className="flex justify-between items-center">
                    
                    <div className="flex items-center gap-4">
                      {/* Icon Circle */}
                      <div className="size-10 rounded-full flex items-center justify-center bg-muted shrink-0 text-xl shadow-inner">
                        {env.icon || "💰"}
                      </div>
                      
                      {/* Name & Left Amount */}
                      <div className="flex flex-col">
                        <span className="text-sm md:text-base font-bold truncate max-w-[140px] md:max-w-[180px]">
                          {env.name}
                        </span>
                        <span className="text-xs text-muted-foreground font-medium">
                          Pozostało {(remaining > 0 ? remaining : 0).toLocaleString("pl-PL")} PLN
                        </span>
                      </div>
                    </div>

                    {/* Spent & Limit */}
                    <div className="flex flex-col items-end text-right">
                      <span className="text-sm md:text-base font-black">
                        {env.spent.toLocaleString("pl-PL")} PLN
                      </span>
                      <span className="text-xs text-muted-foreground font-medium">
                        z {env.limit.toLocaleString("pl-PL")}
                      </span>
                    </div>

                  </div>
                  
                  {/* Progress Bar */}
                  <div className="relative pt-1">
                    <Progress 
                      value={percentage} 
                      className={cn(
                        "h-1.5",
                        isOverLimit ? "bg-destructive/20" : "bg-muted"
                      )}
                    />
                    <div 
                      className={cn(
                        "absolute top-0 bottom-0 left-0 transition-all rounded-full",
                        isOverLimit ? "bg-destructive" : ""
                      )}
                      style={{ 
                        width: `${percentage}%`,
                        backgroundColor: !isOverLimit ? env.color : undefined 
                      }}
                    />
                  </div>
                </div>
              );
            })
          ) : (
            <div className="flex flex-col items-center justify-center text-center py-12 space-y-2">
              <p className="text-sm text-muted-foreground">Brak ustawionych limitów.</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
