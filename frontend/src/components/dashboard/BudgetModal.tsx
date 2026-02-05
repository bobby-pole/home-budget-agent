import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
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
import { Loader2, Save } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useEffect } from "react";

const formSchema = z.object({
  amount: z.coerce.number().min(0, "Kwota musi być dodatnia"),
});

interface BudgetModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentAmount: number;
  year: number;
  month: number;
}

type FormValues = z.infer<typeof formSchema>;

export function BudgetModal({
  isOpen,
  onClose,
  currentAmount,
  year,
  month,
}: BudgetModalProps) {
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: { amount: currentAmount },
  });

  useEffect(() => {
    if (isOpen) form.reset({ amount: currentAmount });
  }, [isOpen, currentAmount, form]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.setBudget({ year, month, amount: values.amount }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budget", year, month] });
      toast.success("Budżet został zaktualizowany!");
      onClose();
    },
    onError: () => toast.error("Błąd zapisu budżetu"),
  });

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Ustaw budżet (Przychód)</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit((v) => mutation.mutate(v))} className="space-y-4">
            <FormField
              control={form.control as any}
              name="amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Miesięczny przychód netto (PLN)</FormLabel>
                  <FormControl>
                    <Input type="number" step="0.01" {...field} placeholder="np. 5000" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onClose}>Anuluj</Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <Save className="mr-2 h-4 w-4" /> Zapisz
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
