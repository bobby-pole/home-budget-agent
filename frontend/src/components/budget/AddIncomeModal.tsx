import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { t } from "@/lib/i18n";
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
import { Loader2, Plus } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";

const incomeSchema = z.object({
  amount: z.string().min(1, t("budget.add_income_modal.validation.amount_required")).refine((val) => {
    const num = parseFloat(val);
    return !isNaN(num) && num > 0;
  }, t("budget.add_income_modal.validation.amount_positive")),
  date: z.string().refine((val) => {
    const date = new Date(val);
    const now = new Date();
    now.setHours(23, 59, 59, 999);
    return date <= now;
  }, t("budget.add_income_modal.validation.date_future")),
  merchant_name: z.string().min(1, t("budget.add_income_modal.validation.source_required")),
});

type IncomeFormValues = z.infer<typeof incomeSchema>;

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

interface AddIncomeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddIncomeModal({ open, onOpenChange }: AddIncomeModalProps) {
  const queryClient = useQueryClient();

  const form = useForm<IncomeFormValues>({
    resolver: zodResolver(incomeSchema),
    defaultValues: {
      amount: "",
      date: todayISO(),
      merchant_name: "Wypłata",
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        amount: "",
        date: todayISO(),
        merchant_name: "Wypłata",
      });
    }
  }, [open, form]);

  const mutation = useMutation({
    mutationFn: (values: IncomeFormValues) =>
      api.createManualTransaction({
        merchant_name: values.merchant_name,
        total_amount: parseFloat(values.amount),
        currency: "PLN",
        date: values.date,
        type: "income",
        lines: [],
        tag_ids: [],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      toast.success(t("budget.add_income_modal.toast_success"));
      onOpenChange(false);
    },
    onError: () => toast.error(t("budget.add_income_modal.toast_error")),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("budget.add_income_modal.title")}</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit((v) => mutation.mutate(v))} className="space-y-4">
            <FormField
              control={form.control}
              name="amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("budget.add_income_modal.amount_label")}</FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type="number"
                        step="0.01"
                        placeholder="0.00"
                        className="text-xl font-bold pr-12"
                        {...field}
                      />
                      <div className="absolute inset-y-0 right-4 flex items-center pointer-events-none">
                        <span className="text-muted-foreground font-bold">PLN</span>
                      </div>
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="merchant_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("budget.add_income_modal.source_label")}</FormLabel>
                  <FormControl>
                    <Input placeholder={t("budget.add_income_modal.placeholder_source")} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="date"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("budget.add_income_modal.date_label")}</FormLabel>
                  <FormControl>
                    <Input type="date" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter className="pt-4">
              <Button type="submit" disabled={mutation.isPending} className="w-full rounded-full font-bold">
                {mutation.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Plus className="mr-2 size-4" />}
                {t("budget.add_income_modal.submit_button")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
