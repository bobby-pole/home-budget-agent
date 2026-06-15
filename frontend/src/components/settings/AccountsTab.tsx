import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Wallet, Plus, X, Pencil } from "lucide-react";
import { toast } from "sonner";
import type { AccountCreate, AccountUpdate, AccountRead } from "@/client";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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

export function AccountsTab() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formData, setFormData] = useState<AccountCreate>({
    name: "",
    type: "checking",
    currency: "PLN",
    initial_balance: 0,
    current_balance: 0,
    is_on_budget: true,
    is_active: true,
    category_id: undefined
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const { data: accounts, isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const createMutation = useMutation({
    mutationFn: (data: AccountCreate) => api.createAccount(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setIsDialogOpen(false);
      resetForm();
      toast.success(t("settings.accounts.toast_created"));
    },
    onError: () => toast.error(t("settings.accounts.toast_create_error")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AccountUpdate }) => api.updateAccount(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setIsDialogOpen(false);
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

  const resetForm = () => {
    setEditingId(null);
    setFormData({
      name: "",
      type: "checking",
      currency: "PLN",
      initial_balance: 0,
      current_balance: 0,
      is_on_budget: true,
      is_active: true
    });
  };

  const handleOpenEdit = (account: AccountRead) => {
    setEditingId(account.id);
    setFormData({
      name: account.name,
      type: account.type || "checking",
      currency: account.currency || "PLN",
      initial_balance: account.initial_balance || 0,
      current_balance: account.current_balance || 0,
      is_on_budget: account.is_on_budget ?? true,
      is_active: account.is_active ?? true,
      category_id: account.category_id ?? undefined
    });
    setIsDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) return;

    if (editingId) {
      updateMutation.mutate({ id: editingId, data: formData });
    } else {
      createMutation.mutate(formData);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-card p-6 rounded-xl border shadow-sm">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-medium flex items-center gap-2">
            <Wallet className="h-5 w-5 text-primary" />
            {t("settings.accounts.section_title")}
          </h3>
          
          <Dialog open={isDialogOpen} onOpenChange={(open) => {
            if (!open) resetForm();
            setIsDialogOpen(open);
          }}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4 mr-2" /> {t("settings.accounts.add_button")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingId ? t("settings.accounts.add_button") : t("settings.accounts.add_button")}
                </DialogTitle>
              </DialogHeader>
              <form onSubmit={handleSubmit} className="space-y-4 pt-4">
                <div className="space-y-2">
                  <Label htmlFor="name">{t("settings.accounts.form.name")}</Label>
                  <Input 
                    id="name"
                    value={formData.name}
                    onChange={(e) => setFormData({...formData, name: e.target.value})}
                    required
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="type">{t("settings.accounts.form.type")}</Label>
                  <Select 
                    value={formData.type} 
                    onValueChange={(val) => setFormData({...formData, type: val})}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="checking">{t("settings.accounts.form.types.checking")}</SelectItem>
                      <SelectItem value="savings">{t("settings.accounts.form.types.savings")}</SelectItem>
                      <SelectItem value="cash">{t("settings.accounts.form.types.cash")}</SelectItem>
                      <SelectItem value="credit">{t("settings.accounts.form.types.credit")}</SelectItem>
                      <SelectItem value="tracking_asset">{t("settings.accounts.form.types.tracking_asset")}</SelectItem>
                      <SelectItem value="tracking_liability">{t("settings.accounts.form.types.tracking_liability")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="category_id">{t("settings.accounts.form.linked_envelope")}</Label>
                  <Select 
                    value={formData.category_id ? formData.category_id.toString() : "none"} 
                    onValueChange={(val) => setFormData({...formData, category_id: val === "none" ? undefined : parseInt(val)})}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t("settings.accounts.form.linked_envelope_placeholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("settings.accounts.form.linked_envelope_none")}</SelectItem>
                      {categories.map(cat => (
                        <SelectItem key={cat.id} value={cat.id.toString()}>{cat.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="initial_balance">{t("settings.accounts.form.initial_balance")}</Label>
                  <Input 
                    id="initial_balance"
                    type="number"
                    step="0.01"
                    value={formData.initial_balance}
                    onChange={(e) => setFormData({...formData, initial_balance: parseFloat(e.target.value) || 0})}
                  />
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <input 
                    type="checkbox" 
                    id="is_on_budget"
                    checked={formData.is_on_budget}
                    onChange={(e) => setFormData({...formData, is_on_budget: e.target.checked})}
                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <div className="space-y-0.5">
                    <Label htmlFor="is_on_budget" className="text-sm font-medium">{t("settings.accounts.form.is_on_budget")}</Label>
                    <p className="text-xs text-muted-foreground">
                      {t("settings.accounts.form.is_on_budget_desc")}
                    </p>
                  </div>
                </div>

                <div className="pt-4 flex justify-end gap-2">
                  <Button type="button" variant="outline" onClick={() => setIsDialogOpen(false)}>
                    {t("settings.accounts.delete_dialog_cancel")}
                  </Button>
                  <Button type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                    {t("settings.accounts.toast_saved")}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        </div>

        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            <div className="h-12 bg-muted rounded-lg w-full"></div>
            <div className="h-12 bg-muted rounded-lg w-full"></div>
          </div>
        ) : accounts?.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("settings.accounts.no_accounts")}</p>
        ) : (
          <div className="space-y-3">
            {accounts?.map((account) => (
              <div key={account.id} className="flex items-center justify-between p-4 rounded-lg border bg-card hover:bg-accent/50 transition-colors">
                <div>
                  <div className="font-medium flex items-center gap-2">
                    {account.name}
                    {!account.is_on_budget && (
                      <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded-full">
                        {t("settings.accounts.off_budget")}
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-muted-foreground flex items-center gap-2 mt-1">
                    <span>{t(`settings.accounts.form.types.${account.type || 'checking'}`)}</span>
                    <span>&bull;</span>
                    <span className="font-mono">{(account.current_balance || 0).toFixed(2)} {account.currency}</span>
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="icon" onClick={() => handleOpenEdit(account)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive hover:bg-destructive/10">
                        <X className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t("settings.accounts.delete_dialog_title")}</AlertDialogTitle>
                        <AlertDialogDescription>
                          {t("settings.accounts.delete_dialog_description")}
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t("settings.accounts.delete_dialog_cancel")}</AlertDialogCancel>
                        <AlertDialogAction
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          onClick={() => deleteMutation.mutate(account.id)}
                        >
                          {t("settings.accounts.delete_dialog_confirm")}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
