import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Card } from "@/components/ui/card";
import { Landmark, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import type { AccountRead } from "@/client";

export function AccountsPage() {
  const queryClient = useQueryClient();
  const [reconcileAccount, setReconcileAccount] = useState<AccountRead | null>(null);
  const [realBalance, setRealBalance] = useState("");

  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const reconcileMutation = useMutation({
    mutationFn: (data: { accountId: number; realBalance: number }) =>
      api.reconcileAccount(data.accountId, data.realBalance),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success(t("accounts.toast_reconciled"));
      setReconcileAccount(null);
    },
    onError: () => {
      toast.error(t("accounts.toast_reconcile_error"));
    },
  });

  const handleReconcile = () => {
    if (!reconcileAccount) return;
    const val = parseFloat(realBalance.replace(",", "."));
    if (isNaN(val)) return;
    reconcileMutation.mutate({ accountId: reconcileAccount.id, realBalance: val });
  };

  return (
    <div className="p-4 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("accounts.title")}</h1>
      </div>

      <Card className="rounded-2xl border-border/50 overflow-hidden shadow-sm">
        {accounts && accounts.length > 0 ? (
          <div className="divide-y divide-border/50">
            {accounts.map(acc => (
              <div key={acc.id} className="flex flex-col sm:flex-row sm:items-center justify-between p-4 hover:bg-muted/50 transition-colors gap-4">
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="size-10 rounded-full bg-emerald-500/10 text-emerald-500 flex items-center justify-center shrink-0">
                    <Landmark className="size-5" />
                  </div>
                  <div>
                    <span className="font-medium truncate block">{acc.name}</span>
                  </div>
                </div>
                <div className="flex flex-row items-center justify-between sm:justify-end gap-4 w-full sm:w-auto">
                  <span className={cn(
                    "font-bold shrink-0 tabular-nums text-lg",
                    (acc.current_balance ?? 0) < 0 ? "text-destructive" : ""
                  )}>
                    {(acc.current_balance ?? 0).toFixed(2)} {acc.currency}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setReconcileAccount(acc);
                      setRealBalance((acc.current_balance ?? 0).toString());
                    }}
                  >
                    <Scale className="size-4 mr-2" />
                    {t("accounts.reconcile_button")}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-sm text-muted-foreground italic text-center">
            {t("more.no_accounts")}
          </div>
        )}
      </Card>

      <Dialog open={!!reconcileAccount} onOpenChange={(open) => !open && setReconcileAccount(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("accounts.reconcile_dialog_title")}</DialogTitle>
            <DialogDescription>
              {t("accounts.reconcile_dialog_description")}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="realBalance">{t("accounts.real_balance")}</Label>
            <div className="flex items-center gap-2 mt-2">
              <Input
                id="realBalance"
                type="number"
                step="0.01"
                value={realBalance}
                onChange={(e) => setRealBalance(e.target.value)}
              />
              <span className="text-muted-foreground shrink-0">{reconcileAccount?.currency}</span>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReconcileAccount(null)} disabled={reconcileMutation.isPending}>
              {t("accounts.reconcile_cancel")}
            </Button>
            <Button onClick={handleReconcile} disabled={reconcileMutation.isPending}>
              {t("accounts.reconcile_confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
