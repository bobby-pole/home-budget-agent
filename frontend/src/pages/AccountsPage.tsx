import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Card } from "@/components/ui/card";
import {
  Landmark,
  PiggyBank,
  Banknote,
  CreditCard,
  TrendingUp,
  ShieldAlert,
  Scale,
  Plus,
  Pencil,
  Trash2,
  Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getIntlLocale } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import type { AccountRead, AccountCreate, AccountUpdate } from "@/client";

function getAccountIcon(type?: string) {
  switch (type) {
    case "savings":
      return <PiggyBank className="size-5 text-emerald-500" />;
    case "cash":
      return <Banknote className="size-5 text-amber-500" />;
    case "credit":
      return <CreditCard className="size-5 text-rose-500" />;
    case "tracking_asset":
      return <TrendingUp className="size-5 text-blue-500" />;
    case "tracking_liability":
      return <ShieldAlert className="size-5 text-destructive" />;
    case "checking":
    default:
      return <Landmark className="size-5 text-primary" />;
  }
}

function getAccountTypeLabel(type?: string): string {
  switch (type) {
    case "savings":
      return t("settings.accounts.form.types.savings");
    case "cash":
      return t("settings.accounts.form.types.cash");
    case "credit":
      return t("settings.accounts.form.types.credit");
    case "tracking_asset":
      return t("settings.accounts.form.types.tracking_asset");
    case "tracking_liability":
      return t("settings.accounts.form.types.tracking_liability");
    case "checking":
    default:
      return t("settings.accounts.form.types.checking");
  }
}

const defaultAccountForm: AccountCreate = {
  name: "",
  type: "checking",
  currency: "PLN",
  initial_balance: 0,
  current_balance: 0,
  is_on_budget: true,
  is_active: true,
  category_id: undefined,
};

export function AccountsPage() {
  const queryClient = useQueryClient();

  // Reconcile state
  const [reconcileAccount, setReconcileAccount] = useState<AccountRead | null>(null);
  const [realBalance, setRealBalance] = useState("");

  // Create / Edit modal state
  const [isAccountDialogOpen, setIsAccountDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<AccountRead | null>(null);
  const [formData, setFormData] = useState<AccountCreate>(defaultAccountForm);

  const { data: accounts, isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const createMutation = useMutation({
    mutationFn: (data: AccountCreate) => api.createAccount(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setIsAccountDialogOpen(false);
      resetForm();
      toast.success(t("settings.accounts.toast_created"));
    },
    onError: () => toast.error(t("settings.accounts.toast_create_error")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AccountUpdate }) =>
      api.updateAccount(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setIsAccountDialogOpen(false);
      resetForm();
      toast.success(t("settings.accounts.toast_saved"));
    },
    onError: () => toast.error(t("settings.accounts.toast_save_error")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteAccount(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(t("settings.accounts.toast_deleted"));
    },
    onError: () => toast.error(t("settings.accounts.toast_delete_error")),
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

  const resetForm = () => {
    setEditingAccount(null);
    setFormData(defaultAccountForm);
  };

  const handleOpenCreate = () => {
    resetForm();
    setIsAccountDialogOpen(true);
  };

  const handleOpenEdit = (account: AccountRead) => {
    setEditingAccount(account);
    setFormData({
      name: account.name,
      type: account.type || "checking",
      currency: account.currency || "PLN",
      initial_balance: account.initial_balance || 0,
      current_balance: account.current_balance || 0,
      is_on_budget: account.is_on_budget ?? true,
      is_active: account.is_active ?? true,
      category_id: account.category_id ?? undefined,
    });
    setIsAccountDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) return;

    if (editingAccount) {
      const details: AccountUpdate = {
        name: formData.name,
        type: formData.type,
        currency: formData.currency,
        is_on_budget: formData.is_on_budget,
        category_id: formData.category_id,
      };
      updateMutation.mutate({ id: editingAccount.id, data: details });
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleReconcile = () => {
    if (!reconcileAccount) return;
    const val = parseFloat(realBalance.replace(",", "."));
    if (isNaN(val)) return;
    reconcileMutation.mutate({ accountId: reconcileAccount.id, realBalance: val });
  };

  return (
    <div className="p-4 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight">{t("accounts.title")}</h1>
          <p className="text-muted-foreground text-sm font-medium mt-0.5">
            {t("accounts.subtitle")}
          </p>
        </div>
        <Button onClick={handleOpenCreate} className="rounded-full font-bold shadow-sm">
          <Plus className="size-4 mr-2" />
          {t("accounts.add_button")}
        </Button>
      </div>

      {/* Accounts List Card */}
      <Card className="rounded-2xl border-border/50 overflow-hidden shadow-sm">
        {isLoading ? (
          <div className="p-6 space-y-4 animate-pulse">
            <div className="h-14 bg-muted rounded-xl w-full" />
            <div className="h-14 bg-muted rounded-xl w-full" />
          </div>
        ) : accounts && accounts.length > 0 ? (
          <div className="divide-y divide-border/50">
            {accounts.map((acc) => (
              <div
                key={acc.id}
                className="flex flex-col sm:flex-row sm:items-center justify-between p-4 hover:bg-muted/40 transition-colors gap-4"
              >
                {/* Account Details */}
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="size-10 rounded-full bg-muted flex items-center justify-center shrink-0">
                    {getAccountIcon(acc.type)}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-bold truncate block">{acc.name}</span>
                      {!acc.is_on_budget && (
                        <span className="text-[10px] bg-muted text-muted-foreground px-2 py-0.5 rounded-full font-semibold">
                          {t("settings.accounts.off_budget")}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground font-medium block">
                      {getAccountTypeLabel(acc.type)}
                    </span>
                  </div>
                </div>

                {/* Balance & Actions */}
                <div className="flex flex-row items-center justify-between sm:justify-end gap-3 w-full sm:w-auto">
                  <span
                    className={cn(
                      "font-bold shrink-0 tabular-nums text-lg",
                      (acc.current_balance ?? 0) < 0 ? "text-destructive" : "text-foreground"
                    )}
                  >
                    {(acc.current_balance ?? 0).toLocaleString(getIntlLocale(), {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}{" "}
                    <span className="text-xs font-semibold text-muted-foreground">
                      {acc.currency}
                    </span>
                  </span>

                  <div className="flex items-center gap-1">
                    {/* Reconcile Button */}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setReconcileAccount(acc);
                        setRealBalance((acc.current_balance ?? 0).toString());
                      }}
                      title={t("accounts.reconcile_button")}
                    >
                      <Scale className="size-4 mr-1.5" />
                      <span className="hidden md:inline">{t("accounts.reconcile_button")}</span>
                    </Button>

                    {/* Edit Account Button */}
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleOpenEdit(acc)}
                      title={t("accounts.edit_account")}
                      className="size-8"
                    >
                      <Pencil className="size-4" />
                    </Button>

                    {/* Delete Account AlertDialog */}
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                          title={t("accounts.delete_button")}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>
                            {t("settings.accounts.delete_dialog_title")}
                          </AlertDialogTitle>
                          <AlertDialogDescription>
                            {t("settings.accounts.delete_dialog_description")}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>
                            {t("settings.accounts.delete_dialog_cancel")}
                          </AlertDialogCancel>
                          <AlertDialogAction
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            onClick={() => deleteMutation.mutate(acc.id)}
                          >
                            {t("settings.accounts.delete_dialog_confirm")}
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-12 text-sm text-muted-foreground italic text-center space-y-3">
            <Wallet className="size-8 mx-auto opacity-40" />
            <p>{t("settings.accounts.no_accounts")}</p>
            <Button size="sm" variant="outline" onClick={handleOpenCreate}>
              <Plus className="size-4 mr-1.5" />
              {t("accounts.add_button")}
            </Button>
          </div>
        )}
      </Card>

      {/* Add / Edit Account Dialog */}
      <Dialog
        open={isAccountDialogOpen}
        onOpenChange={(open) => {
          if (!open) resetForm();
          setIsAccountDialogOpen(open);
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>
              {editingAccount ? t("accounts.edit_account") : t("accounts.create_account")}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4 pt-2">
            <div className="space-y-2">
              <Label htmlFor="account_name">{t("settings.accounts.form.name")}</Label>
              <Input
                id="account_name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="account_type">{t("settings.accounts.form.type")}</Label>
              <Select
                value={formData.type}
                onValueChange={(val) => setFormData({ ...formData, type: val })}
              >
                <SelectTrigger id="account_type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="checking">
                    {t("settings.accounts.form.types.checking")}
                  </SelectItem>
                  <SelectItem value="savings">
                    {t("settings.accounts.form.types.savings")}
                  </SelectItem>
                  <SelectItem value="cash">{t("settings.accounts.form.types.cash")}</SelectItem>
                  <SelectItem value="credit">
                    {t("settings.accounts.form.types.credit")}
                  </SelectItem>
                  <SelectItem value="tracking_asset">
                    {t("settings.accounts.form.types.tracking_asset")}
                  </SelectItem>
                  <SelectItem value="tracking_liability">
                    {t("settings.accounts.form.types.tracking_liability")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="account_category">{t("settings.accounts.form.linked_envelope")}</Label>
              <Select
                value={formData.category_id ? formData.category_id.toString() : "none"}
                onValueChange={(val) =>
                  setFormData({
                    ...formData,
                    category_id: val === "none" ? undefined : parseInt(val),
                  })
                }
              >
                <SelectTrigger id="account_category">
                  <SelectValue placeholder={t("settings.accounts.form.linked_envelope_placeholder")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">
                    {t("settings.accounts.form.linked_envelope_none")}
                  </SelectItem>
                  {categories.map((cat) => (
                    <SelectItem key={cat.id} value={cat.id.toString()}>
                      {cat.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="account_initial_balance">
                {t("settings.accounts.form.initial_balance")}
              </Label>
              <Input
                id="account_initial_balance"
                type="number"
                step="0.01"
                value={formData.initial_balance}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    initial_balance: parseFloat(e.target.value) || 0,
                  })
                }
                disabled={editingAccount !== null}
              />
            </div>

            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="account_is_on_budget"
                checked={formData.is_on_budget}
                onChange={(e) => setFormData({ ...formData, is_on_budget: e.target.checked })}
                className="size-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <div className="space-y-0.5">
                <Label htmlFor="account_is_on_budget" className="text-sm font-medium">
                  {t("settings.accounts.form.is_on_budget")}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t("settings.accounts.form.is_on_budget_desc")}
                </p>
              </div>
            </div>

            <DialogFooter className="pt-4">
              <Button type="button" variant="outline" onClick={() => setIsAccountDialogOpen(false)}>
                {t("settings.accounts.delete_dialog_cancel")}
              </Button>
              <Button
                type="submit"
                disabled={createMutation.isPending || updateMutation.isPending}
              >
                {t("settings.accounts.toast_saved")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Reconcile Dialog */}
      <Dialog
        open={!!reconcileAccount}
        onOpenChange={(open) => !open && setReconcileAccount(null)}
      >
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
              <span className="text-muted-foreground shrink-0">
                {reconcileAccount?.currency}
              </span>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setReconcileAccount(null)}
              disabled={reconcileMutation.isPending}
            >
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
