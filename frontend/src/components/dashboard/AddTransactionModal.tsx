import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Form } from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { Loader2, Save } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { transactionSchema, type TransactionFormInput, type TransactionFormValues } from "./transaction/schema";
import { TransactionHeaderSection } from "./transaction/TransactionHeaderSection";
import { TransactionMetaSection } from "./transaction/TransactionMetaSection";
import { ItemsPanel, type ManualItem } from "./transaction/ItemsPanel";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

interface AddTransactionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddTransactionModal({ open, onOpenChange }: AddTransactionModalProps) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<ManualItem[]>([]);

  const hasItems = items.length > 0;
  const computedTotal = items.reduce((sum, i) => sum + i.price * i.quantity, 0);

  const form = useForm<TransactionFormInput, unknown, TransactionFormValues>({
    resolver: zodResolver(transactionSchema),
    defaultValues: {
      merchant_name: "",
      total_amount: undefined,
      currency: "PLN",
      date: todayISO(),
      category_id: "",
      note: "",
      tag_ids: [],
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        merchant_name: "",
        total_amount: undefined,
        currency: "PLN",
        date: todayISO(),
        category_id: "",
        note: "",
        tag_ids: [],
      });
    }
  }, [open, form]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open) setItems([]);
  }, [open]);

  const currency = useWatch({ control: form.control, name: "currency", defaultValue: "PLN" });

  const mutation = useMutation({
    mutationFn: (values: TransactionFormValues) =>
      api.createManualTransaction({
        merchant_name: values.merchant_name,
        total_amount: hasItems ? computedTotal : (values.total_amount ?? 0),
        currency: values.currency,
        date: values.date || undefined,
        category_id: hasItems ? undefined : (values.category_id ? parseInt(values.category_id) : undefined),
        note: hasItems ? undefined : (values.note || undefined),
        tag_ids: values.tag_ids,
        items: hasItems
          ? items.map(({ name, price, quantity, category }) => ({ name, price, quantity, category }))
          : [],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Transakcja dodana");
      onOpenChange(false);
    },
    onError: () => toast.error("Błąd zapisu transakcji"),
  });

  const onSubmit = (values: TransactionFormValues) => {
    if (!hasItems && !values.total_amount) {
      form.setError("total_amount", { message: "Wymagane gdy brak pozycji" });
      return;
    }
    mutation.mutate(values);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[640px] max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-2 border-b mb-4">
          <DialogTitle>Dodaj transakcję ręcznie</DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-1 space-y-4">
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <TransactionHeaderSection
                control={form.control}
                hasItems={hasItems}
                computedTotal={computedTotal}
                currency={currency}
              />

              {!hasItems && <TransactionMetaSection control={form.control} />}

              <ItemsPanel items={items} currency={currency} onItemsChange={setItems} />

              <div className="flex justify-end gap-2 pb-2 border-b">
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  <Save className="mr-2 h-4 w-4" />
                  Zapisz transakcję
                </Button>
              </div>
            </form>
          </Form>
        </div>

        <DialogFooter className="mt-4 pt-2 border-t">
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
