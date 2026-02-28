import { useState, useEffect } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
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
import { Loader2, Save, Pencil } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { Receipt } from "@/types";
import { SectionGrid } from "../shared/SectionGrid";

const formSchema = z.object({
  merchant_name: z.string().min(1, "Nazwa sklepu jest wymagana"),
  date: z.string().refine((val) => !isNaN(Date.parse(val)), {
    message: "Nieprawidłowa data",
  }),
  total_amount: z.coerce.number().min(0.01, "Kwota musi być większa od 0"),
  currency: z.string().min(3, "Waluta musi mieć 3 znaki").max(3),
});

type FormValues = z.infer<typeof formSchema>;

interface ReceiptHeaderFormProps {
  receipt: Receipt;
}

export function ReceiptHeaderForm({ receipt }: ReceiptHeaderFormProps) {
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema) as Resolver<FormValues>,
    defaultValues: {
      merchant_name: "",
      date: "",
      total_amount: 0,
      currency: "PLN",
    },
  });

  useEffect(() => {
    form.reset({
      merchant_name: receipt.merchant_name,
      date: receipt.date ? new Date(receipt.date).toISOString().split("T")[0] : "",
      total_amount: receipt.total_amount,
      currency: receipt.currency,
    });
  }, [receipt, form]);

  const updateMutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.updateReceipt(receipt.id, {
        ...values,
        date: new Date(values.date).toISOString(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Zapisano dane nagłówka!");
      setIsEditing(false);
    },
    onError: (err) => {
      console.error(err);
      toast.error("Błąd zapisu.");
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => updateMutation.mutate(values))}
        className="space-y-4"
      >
        <SectionGrid>
          <FormField
            control={form.control}
            name="merchant_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                  Sklep
                </FormLabel>
                {isEditing ? (
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

          <FormField
            control={form.control}
            name="date"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                  Data
                </FormLabel>
                {isEditing ? (
                  <>
                    <FormControl>
                      <Input type="date" {...field} />
                    </FormControl>
                    <FormMessage />
                  </>
                ) : (
                  <div className="text-lg font-medium">{field.value || "-"}</div>
                )}
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="total_amount"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                  Kwota
                </FormLabel>
                {isEditing ? (
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

          <FormField
            control={form.control}
            name="currency"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                  Waluta
                </FormLabel>
                {isEditing ? (
                  <>
                    <FormControl>
                      <Input {...field} maxLength={3} />
                    </FormControl>
                    <FormMessage />
                  </>
                ) : (
                  <div className="text-lg font-medium">{field.value}</div>
                )}
              </FormItem>
            )}
          />
        </SectionGrid>

        <div className="flex justify-end gap-2 pb-2 border-b">
          {!isEditing ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={(e) => {
                e.preventDefault();
                setIsEditing(true);
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
                  setIsEditing(false);
                }}
              >
                Anuluj
              </Button>
              <Button type="submit" size="sm" disabled={updateMutation.isPending}>
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
  );
}
