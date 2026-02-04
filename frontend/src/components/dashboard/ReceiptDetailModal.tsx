import { useState, useEffect } from "react";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, Save, Pencil } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { Receipt } from "@/types";
import { ReceiptItemRow } from "./ReceiptItemRow";

const formSchema = z.object({
  merchant_name: z.string().min(1, "Nazwa sklepu jest wymagana"),
  date: z.string().refine((val) => !isNaN(Date.parse(val)), {
    message: "Nieprawidłowa data",
  }),
  total_amount: z.coerce.number().min(0.01, "Kwota musi być większa od 0"),
  currency: z.string().min(3, "Waluta musi mieć 3 znaki").max(3),
});

interface ReceiptDetailModalProps {
  receipt: Receipt | null;
  isOpen: boolean;
  onClose: () => void;
}

export function ReceiptDetailModal({
  receipt,
  isOpen,
  onClose,
}: ReceiptDetailModalProps) {
  const queryClient = useQueryClient();
  const [isEditingHeader, setIsEditingHeader] = useState(false);

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      merchant_name: "",
      date: "",
      total_amount: 0,
      currency: "PLN",
    },
  });

  useEffect(() => {
    if (receipt) {
      form.reset({
        merchant_name: receipt.merchant_name,
        date: new Date(receipt.date).toISOString().split("T")[0],
        total_amount: receipt.total_amount,
        currency: receipt.currency,
      });
    }
    if (!isOpen) {
      setIsEditingHeader(false);
    }
  }, [receipt, form, isOpen]);

  const updateMutation = useMutation({
    mutationFn: (values: z.infer<typeof formSchema>) => {
      if (!receipt) throw new Error("No receipt selected");
      return api.updateReceipt(receipt.id, {
        ...values,
        date: new Date(values.date).toISOString(),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Zapisano dane nagłówka!");
      setIsEditingHeader(false);
    },
    onError: (err) => {
      console.error(err);
      toast.error("Błąd zapisu.");
    },
  });

  function onSubmit(values: z.infer<typeof formSchema>) {
    updateMutation.mutate(values);
  }

  if (!receipt) return null;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[650px] max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-2 border-b mb-4">
          <DialogTitle>Szczegóły paragonu #{receipt.id}</DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-1 space-y-6">
          {/* SEKCJA NAGŁÓWKA */}
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-6 p-4 border rounded-lg bg-muted/20">
                {/* Sklep */}
                <FormField
                  control={form.control}
                  name="merchant_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                        Sklep
                      </FormLabel>
                      {isEditingHeader ? (
                        <>
                          <FormControl>
                            <Input {...field} />
                          </FormControl>
                          <FormMessage />
                        </>
                      ) : (
                        <div className="text-lg font-medium truncate" title={field.value}>
                          {field.value}
                        </div>
                      )}
                    </FormItem>
                  )}
                />

                {/* Data */}
                <FormField
                  control={form.control}
                  name="date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                        Data
                      </FormLabel>
                      {isEditingHeader ? (
                        <>
                          <FormControl>
                            <Input type="date" {...field} />
                          </FormControl>
                          <FormMessage />
                        </>
                      ) : (
                        <div className="text-lg font-medium">
                          {field.value}
                        </div>
                      )}
                    </FormItem>
                  )}
                />

                {/* Kwota */}
                <FormField
                  control={form.control}
                  name="total_amount"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                        Kwota
                      </FormLabel>
                      {isEditingHeader ? (
                        <>
                          <FormControl>
                            <Input type="number" step="0.01" {...field} />
                          </FormControl>
                          <FormMessage />
                        </>
                      ) : (
                        <div className="text-lg font-bold text-primary">
                          {Number(field.value).toFixed(2)}
                        </div>
                      )}
                    </FormItem>
                  )}
                />

                {/* Waluta */}
                <FormField
                  control={form.control}
                  name="currency"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                        Waluta
                      </FormLabel>
                      {isEditingHeader ? (
                        <>
                          <FormControl>
                            <Input {...field} maxLength={3} />
                          </FormControl>
                          <FormMessage />
                        </>
                      ) : (
                        <div className="text-lg font-medium">
                          {field.value}
                        </div>
                      )}
                    </FormItem>
                  )}
                />
              </div>

              {/* PRZYCISKI AKCJI POD NAGŁÓWKIEM */}
              <div className="flex justify-end gap-2 pb-2 border-b">
                {!isEditingHeader ? (
                  <Button
                    type="button" // Ważne: type="button" zapobiega submitowi
                    variant="outline"
                    size="sm"
                    onClick={(e) => {
                      e.preventDefault(); // Dodatkowe zabezpieczenie
                      setIsEditingHeader(true);
                    }}
                  >
                    <Pencil className="mr-2 h-4 w-4" />
                    Edytuj dane
                  </Button>
                ) : (
                  <>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        form.reset();
                        setIsEditingHeader(false);
                      }}
                    >
                      Anuluj
                    </Button>
                    <Button
                      type="submit"
                      size="sm"
                      disabled={updateMutation.isPending}
                    >
                      {updateMutation.isPending && (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      )}
                      <Save className="mr-2 h-4 w-4" />
                      Zapisz
                    </Button>
                  </>
                )}
              </div>
            </form>
          </Form>

          {/* SEKCJA POZYCJI */}
          <div>
            <h4 className="mb-3 text-sm font-semibold text-muted-foreground flex items-center gap-2">
              Pozycje na paragonie
              <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded-full text-xs">
                {receipt.items?.length || 0}
              </span>
            </h4>
            <ScrollArea className="h-[300px] rounded-md border bg-card">
              {receipt.items?.length ? (
                <div className="divide-y">
                  {receipt.items.map((item) => (
                    <ReceiptItemRow
                      key={item.id}
                      item={item}
                      currency={receipt.currency}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm p-4">
                  <p>Brak wykrytych pozycji.</p>
                </div>
              )}
            </ScrollArea>
          </div>
        </div>

        {/* STOPKA MODALA */}
        <DialogFooter className="mt-4 pt-2 border-t">
          <Button type="button" variant="secondary" onClick={onClose}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
