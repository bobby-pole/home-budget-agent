import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Card } from "@/components/ui/card";
import { Landmark } from "lucide-react";
import { cn } from "@/lib/utils";

export function AccountsPage() {
  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  return (
    <div className="p-4 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("accounts.title")}</h1>
      </div>

      <Card className="rounded-2xl border-border/50 overflow-hidden shadow-sm">
        {accounts && accounts.length > 0 ? (
          <div className="divide-y divide-border/50">
            {accounts.map(acc => (
              <div key={acc.id} className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors">
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="size-10 rounded-full bg-emerald-500/10 text-emerald-500 flex items-center justify-center shrink-0">
                    <Landmark className="size-5" />
                  </div>
                  <div>
                    <span className="font-medium truncate block">{acc.name}</span>
                  </div>
                </div>
                <span className={cn(
                  "font-bold shrink-0 tabular-nums ml-2 text-right text-lg",
                  (acc.current_balance ?? 0) < 0 ? "text-destructive" : ""
                )}>
                  {(acc.current_balance ?? 0).toFixed(2)} {acc.currency}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-sm text-muted-foreground italic text-center">
            {t("more.no_accounts")}
          </div>
        )}
      </Card>
    </div>
  );
}
