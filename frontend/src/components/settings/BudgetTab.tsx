import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { t } from "@/lib/i18n";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, UserPlus } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { type BudgetMemberCreate } from "@/client";

const inviteSchema = z.object({
  email: z.string().email(t("settings.budget_tab.validation.email_invalid")),
  role: z.enum(["owner", "editor", "viewer"]),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

export function BudgetTab() {
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);

  const form = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: {
      email: "",
      role: "editor",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: InviteFormValues) => api.inviteMember(values as BudgetMemberCreate),
    onSuccess: () => {
      toast.success(t("settings.budget_tab.toast_invited"));
      setIsInviteModalOpen(false);
      form.reset();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message = error.response?.data?.detail || t("settings.budget_tab.toast_invite_error");
      toast.error(message);
    },
  });

  const onSubmit = (values: InviteFormValues) => {
    mutation.mutate(values);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.budget_tab.card_title")}</CardTitle>
          <CardDescription>
            {t("settings.budget_tab.card_description")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setIsInviteModalOpen(true)}>
            <UserPlus className="mr-2 h-4 w-4" />
            {t("settings.budget_tab.invite_button")}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={isInviteModalOpen} onOpenChange={setIsInviteModalOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t("settings.budget_tab.invite_dialog_title")}</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 pt-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("settings.budget_tab.invite_email_label")}</FormLabel>
                    <FormControl>
                      <Input placeholder={t("settings.budget_tab.placeholder_email")} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("settings.budget_tab.invite_role_label")}</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={t("settings.budget_tab.placeholder_role")} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="owner">{t("settings.budget_tab.invite_role_owner")}</SelectItem>
                        <SelectItem value="editor">{t("settings.budget_tab.invite_role_editor")}</SelectItem>
                        <SelectItem value="viewer">{t("settings.budget_tab.invite_role_viewer")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter className="pt-4">
                <Button type="button" variant="outline" onClick={() => setIsInviteModalOpen(false)}>
                  {t("settings.budget_tab.invite_cancel")}
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {t("settings.budget_tab.invite_submit")}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
