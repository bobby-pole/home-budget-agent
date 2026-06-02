import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { Trash2, UserPlus, CheckCircle, Shield, Plus, Pencil } from "lucide-react";
import type { BudgetMemberCreate, UserBudgetRead } from "@/client";

const passwordSchema = z.object({
  old_password: z.string().min(1, t("profile.old_password_required")),
  new_password: z.string().min(6, t("profile.password_min")),
  confirm_password: z.string().min(1, t("profile.confirm_required")),
}).refine((data) => data.new_password === data.confirm_password, {
  message: t("profile.passwords_dont_match"),
  path: ["confirm_password"],
});

type PasswordFormValues = z.infer<typeof passwordSchema>;

const inviteSchema = z.object({
  email: z.string().email(t("profile.email_invalid")),
  role: z.enum(["owner", "editor", "viewer"]),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

const budgetNameSchema = z.object({
  name: z.string().min(1, t("profile.budget_name_required")),
});

type BudgetNameFormValues = z.infer<typeof budgetNameSchema>;

export function ProfilePage() {
  const { user, activeBudgetId, switchBudget, updateUser } = useAuth();
  const queryClient = useQueryClient();
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [budgetToDelete, setBudgetToDelete] = useState<number | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [isCreateBudgetModalOpen, setIsCreateBudgetModalOpen] = useState(false);
  const [budgetToRename, setBudgetToRename] = useState<{id: number, name: string} | null>(null);

  const { data: budgets = [], isLoading } = useQuery({
    queryKey: ["my-budgets"],
    queryFn: api.getMyBudgets,
  });

  const activeBudget = budgets.find(b => b.id === activeBudgetId) || budgets?.[0];
  const isOwner = activeBudget?.role === "owner";
  const canInvite = isOwner;

  // Password Form
  const passwordForm = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { old_password: "", new_password: "", confirm_password: "" },
  });

  const passwordMutation = useMutation({
    mutationFn: (values: PasswordFormValues) => api.changePassword({
      old_password: values.old_password,
      new_password: values.new_password,
    }),
    onSuccess: () => {
      toast.success(t("profile.success_password"));
      passwordForm.reset();
    },
    onError: () => toast.error(t("profile.error_password")),
  });

  // Invite Form
  const inviteForm = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "editor" },
  });

  const inviteMutation = useMutation({
    mutationFn: (values: InviteFormValues) => api.inviteMember(values as BudgetMemberCreate),
    onSuccess: () => {
      toast.success(t("profile.success_invite"));
      setIsInviteModalOpen(false);
      inviteForm.reset();
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => toast.error(err.response?.data?.detail || t("profile.error_invite")),
  });

  // Set Default Budget
  const defaultBudgetMutation = useMutation({
    mutationFn: (id: number) => api.updateMe({ default_budget_id: id }),
    onSuccess: (updatedUser) => {
      toast.success(t("profile.success_default"));
      updateUser(updatedUser);
    },
    onError: () => toast.error(t("profile.error_default")),
  });

  // Delete Budget
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteBudget(id),
    onSuccess: () => {
      toast.success(t("profile.success_delete"));
      queryClient.invalidateQueries({ queryKey: ["my-budgets"] });
      if (activeBudgetId === budgetToDelete) {
        const freshBudgets = queryClient.getQueryData<UserBudgetRead[]>(["my-budgets"]) || budgets;
        const nextBudget = freshBudgets.find(b => b.id !== budgetToDelete);
        if (nextBudget) switchBudget(nextBudget.id);
      }
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => toast.error(err.response?.data?.detail || t("profile.error_delete_fallback")),
  });

  // Create Budget
  const createBudgetForm = useForm<BudgetNameFormValues>({
    resolver: zodResolver(budgetNameSchema),
    defaultValues: { name: "" },
  });

  const createBudgetMutation = useMutation({
    mutationFn: (values: BudgetNameFormValues) => api.createBudget(values),
    onSuccess: () => {
      toast.success(t("profile.success_create_budget"));
      setIsCreateBudgetModalOpen(false);
      createBudgetForm.reset();
      queryClient.invalidateQueries({ queryKey: ["my-budgets"] });
    },
    onError: () => toast.error(t("profile.error_create_budget")),
  });

  // Rename Budget
  const renameBudgetForm = useForm<BudgetNameFormValues>({
    resolver: zodResolver(budgetNameSchema),
    defaultValues: { name: "" },
  });

  const renameBudgetMutation = useMutation({
    mutationFn: (values: BudgetNameFormValues) => {
      if (!budgetToRename) throw new Error("No budget selected");
      return api.updateBudget(budgetToRename.id, values);
    },
    onSuccess: () => {
      toast.success(t("profile.success_rename_budget"));
      setBudgetToRename(null);
      renameBudgetForm.reset();
      queryClient.invalidateQueries({ queryKey: ["my-budgets"] });
    },
    onError: () => toast.error(t("profile.error_rename_budget")),
  });

  return (
    <div className="p-4 md:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">{t("profile.title")}</h2>
          <p className="text-muted-foreground">{t("profile.subtitle")}</p>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Account Details */}
          <Card>
            <CardHeader>
              <CardTitle>{t("profile.account_details")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                <p className="text-sm font-medium leading-none">{t("profile.email")}</p>
                <p className="text-sm text-muted-foreground">{user?.email}</p>
              </div>
            </CardContent>
          </Card>

          {/* Change Password */}
          <Card>
            <CardHeader>
              <CardTitle>{t("profile.change_password")}</CardTitle>
            </CardHeader>
            <CardContent>
              <Form {...passwordForm}>
                <form onSubmit={passwordForm.handleSubmit((v) => passwordMutation.mutate(v))} className="space-y-4">
                  <FormField
                    control={passwordForm.control}
                    name="old_password"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t("profile.old_password")}</FormLabel>
                        <FormControl><Input type="password" {...field} /></FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={passwordForm.control}
                    name="new_password"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t("profile.new_password")}</FormLabel>
                        <FormControl><Input type="password" {...field} /></FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={passwordForm.control}
                    name="confirm_password"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t("profile.confirm_password")}</FormLabel>
                        <FormControl><Input type="password" {...field} /></FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <Button type="submit" disabled={passwordMutation.isPending}>{t("profile.change_password")}</Button>
                </form>
              </Form>
            </CardContent>
          </Card>
        </div>

        {/* Budgets List */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>{t("profile.my_budgets")}</CardTitle>
              <CardDescription>{t("profile.budgets_subtitle")}</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => setIsCreateBudgetModalOpen(true)}>
              <Plus className="w-4 h-4 mr-2" /> {t("profile.create_budget")}
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            {isLoading ? (
              <p>{t("profile.loading_budgets")}</p>
            ) : (
              <div className="space-y-4">
                {budgets.map((b) => {
                  const isActive = b.id === activeBudget?.id;
                  const isDefault = b.id === user?.default_budget_id;
                  return (
                    <div key={b.id} className={`flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 border rounded-lg ${isActive ? 'bg-muted/50 border-primary' : ''}`}>
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-semibold">{b.name}</h4>
                          {isActive && <span className="flex items-center text-xs bg-primary text-primary-foreground px-2 py-0.5 rounded-full"><CheckCircle className="w-3 h-3 mr-1"/> {t("profile.active")}</span>}
                          {isDefault && <span className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">{t("profile.default")}</span>}
                        </div>
                        <p className="text-sm text-muted-foreground flex items-center mt-1">
                          <Shield className="w-4 h-4 mr-1" />
                          {t("profile.role_label")} <span className="capitalize ml-1">{t(`profile.role_${b.role}`)}</span>
                        </p>
                      </div>
                      <div className="grid grid-cols-[1fr_auto] sm:flex sm:flex-nowrap items-center gap-2 w-full sm:w-auto mt-2 sm:mt-0">
                        <div className="flex gap-2 w-full">
                          {!isDefault && (
                            <Button className="flex-1" variant="secondary" size="sm" onClick={() => defaultBudgetMutation.mutate(b.id)} disabled={defaultBudgetMutation.isPending}>
                              {t("profile.set_default")}
                            </Button>
                          )}
                          {!isActive && (
                            <Button className="flex-1" variant="outline" size="sm" onClick={() => switchBudget(b.id)}>
                              {t("profile.switch")}
                            </Button>
                          )}
                          {isActive && canInvite && (
                            <Button className="flex-1" variant="outline" size="sm" onClick={() => setIsInviteModalOpen(true)}>
                              <UserPlus className="w-4 h-4 mr-1" /> {t("profile.invite")}
                            </Button>
                          )}
                        </div>
                        {b.role === "owner" && (
                          <div className="flex gap-2">
                            <Button variant="outline" size="icon" onClick={() => {
                              setBudgetToRename({ id: b.id, name: b.name });
                              renameBudgetForm.setValue("name", b.name);
                            }}>
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button variant="destructive" size="icon" onClick={() => setBudgetToDelete(b.id)}>
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={isInviteModalOpen} onOpenChange={setIsInviteModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("profile.invite_to_budget")}</DialogTitle>
          </DialogHeader>
          <Form {...inviteForm}>
            <form onSubmit={inviteForm.handleSubmit((v) => inviteMutation.mutate(v))} className="space-y-4">
              <FormField
                control={inviteForm.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("profile.email")}</FormLabel>
                    <FormControl><Input placeholder="user@example.com" {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={inviteForm.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("profile.role")}</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger><SelectValue placeholder={t("profile.role")} /></SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="viewer">{t("profile.role_viewer")}</SelectItem>
                        <SelectItem value="editor">{t("profile.role_editor")}</SelectItem>
                        <SelectItem value="owner">{t("profile.role_owner")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter>
                <Button type="submit" disabled={inviteMutation.isPending}>{t("profile.send_invite")}</Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      <Dialog open={budgetToDelete !== null} onOpenChange={(open) => {
        if (!open) {
          setBudgetToDelete(null);
          setDeleteConfirmText("");
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("profile.delete_budget_title")}</DialogTitle>
            <DialogDescription>
              {t("profile.delete_budget_desc1")}
              <br />
              {t("profile.delete_budget_desc2", { keyword: t("profile.delete_keyword") })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Input
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder={t("profile.type_delete_to_confirm", { keyword: t("profile.delete_keyword") })}
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => {
                setBudgetToDelete(null);
                setDeleteConfirmText("");
              }}>{t("profile.cancel")}</Button>
              <Button
                variant="destructive"
                disabled={deleteConfirmText !== t("profile.delete_keyword") || deleteMutation.isPending}
                onClick={() => {
                  if (budgetToDelete) {
                    deleteMutation.mutate(budgetToDelete);
                    setBudgetToDelete(null);
                    setDeleteConfirmText("");
                  }
                }}
              >
                {t("profile.delete")}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={isCreateBudgetModalOpen} onOpenChange={setIsCreateBudgetModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("profile.create_budget_title")}</DialogTitle>
            <DialogDescription>{t("profile.create_budget_desc")}</DialogDescription>
          </DialogHeader>
          <Form {...createBudgetForm}>
            <form onSubmit={createBudgetForm.handleSubmit((v) => createBudgetMutation.mutate(v))} className="space-y-4">
              <FormField
                control={createBudgetForm.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("profile.budget_name")}</FormLabel>
                    <FormControl><Input placeholder={t("profile.budget_name")} {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter className="gap-2 sm:gap-0">
                <Button type="button" variant="outline" onClick={() => setIsCreateBudgetModalOpen(false)}>
                  {t("common.cancel")}
                </Button>
                <Button type="submit" disabled={createBudgetMutation.isPending}>{t("profile.create")}</Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      <Dialog open={budgetToRename !== null} onOpenChange={(open) => !open && setBudgetToRename(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("profile.rename_budget_title")}</DialogTitle>
            <DialogDescription>{t("profile.rename_budget_desc")}</DialogDescription>
          </DialogHeader>
          <Form {...renameBudgetForm}>
            <form onSubmit={renameBudgetForm.handleSubmit((v) => renameBudgetMutation.mutate(v))} className="space-y-4">
              <FormField
                control={renameBudgetForm.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("profile.budget_name")}</FormLabel>
                    <FormControl><Input placeholder={t("profile.budget_name")} {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter className="gap-2 sm:gap-0">
                <Button type="button" variant="outline" onClick={() => setBudgetToRename(null)}>
                  {t("common.cancel")}
                </Button>
                <Button type="submit" disabled={renameBudgetMutation.isPending}>{t("profile.rename")}</Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
