import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Pencil, Check, X, Loader2 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Form, FormControl, FormField, FormItem } from "@/components/ui/form";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { CATEGORY_LABELS } from "@/lib/constants";
import type { TransactionLine } from "@/types";

const itemSchema = z.object({
  name: z.string().min(1, "Nazwa wymagana"),
  price: z.number().min(0.01),
  quantity: z.number().min(0.1),
  category_id: z.number().nullable(),
});

type FormValues = z.infer<typeof itemSchema>;

interface TransactionItemRowProps {
  item: TransactionLine;
  transactionId: number;
  currency: string;
}

export function TransactionItemRow({ item, transactionId, currency }: TransactionItemRowProps) {
  const [isEditing, setIsEditing] = useState(false);
  const queryClient = useQueryClient();

  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(itemSchema),
    defaultValues: {
      name: item.name,
      price: item.price,
      quantity: item.quantity,
      category_id: item.category_id,
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.updateTransactionLine(transactionId, item.id, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Zaktualizowano pozycję");
      setIsEditing(false);
    },
    onError: () => {
      toast.error("Błąd aktualizacji pozycji");
    },
  });

  const onSubmit = (values: FormValues) => {
    mutation.mutate(values);
  };

  const getDisplayCategory = (categoryId: number | null) => {
    if (!categories || categoryId == null) return null;
    const cat = categories.find((c) => c.id === categoryId);
    if (!cat) return null;
    return {
      name: cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name,
      color: cat.color || "#9ca3af",
      icon: cat.icon || "📦",
    };
  };

  if (!isEditing) {
    const displayCat = getDisplayCategory(item.category_id);

    return (
      <div className="flex items-center justify-between py-2 px-2 text-sm border-b last:border-0 group h-[52px] hover:bg-muted/20 transition-colors min-w-[450px]">
        <div className="flex items-center flex-1 min-w-0 mr-2 gap-3">
          <span className="font-medium truncate shrink" title={item.name}>
            {item.name}
          </span>

          <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground ml-auto">
            {displayCat && (
              <span
                className="px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium flex items-center gap-1 text-white shadow-sm"
                style={{ backgroundColor: displayCat.color }}
              >
                <span>{displayCat.icon}</span> {displayCat.name}
              </span>
            )}
            <span className="w-12 text-right">
              {item.quantity} szt.
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-2">
          <span className="font-semibold whitespace-nowrap min-w-[70px] text-right">
            {item.price.toFixed(2)} {currency}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 opacity-70 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity"
            onClick={() => setIsEditing(true)}
            title="Edytuj pozycję"
          >
            <Pencil className="h-4 w-4 text-muted-foreground" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="py-2 px-2 border-b last:border-0 h-[52px] flex items-center bg-muted/30 min-w-[450px]">
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex items-center gap-2 w-full">
          {/* 1. Nazwa */}
          <div className="flex-1 min-w-0">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="space-y-0">
                  <FormControl>
                    <Input {...field} className="h-8 text-xs bg-background" placeholder="Nazwa" />
                  </FormControl>
                </FormItem>
              )}
            />
          </div>

          {/* 2. Kategoria */}
          <FormField
            control={form.control}
            name="category_id"
            render={({ field }) => (
              <FormItem className="w-32 space-y-0">
                <FormControl>
                  <Select
                    value={field.value != null ? String(field.value) : ""}
                    onValueChange={(val) => field.onChange(val ? parseInt(val) : null)}
                  >
                    <SelectTrigger className="h-8 text-xs px-2 bg-background">
                      <SelectValue placeholder="Kat." />
                    </SelectTrigger>
                    <SelectContent>
                      {categories?.map((cat) => (
                        <SelectItem key={cat.id} value={String(cat.id)}>
                          <span className="flex items-center gap-2">
                            <span>{cat.icon}</span>
                            {cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormControl>
              </FormItem>
            )}
          />

          {/* 3. Ilość */}
          <FormField
            control={form.control}
            name="quantity"
            render={({ field }) => (
              <FormItem className="w-14 space-y-0">
                <FormControl>
                  <Input {...field} type="number" step="0.1" className="h-8 text-xs px-1 text-center bg-background" placeholder="Il." title="Ilość" />
                </FormControl>
              </FormItem>
            )}
          />

          {/* 4. Cena */}
          <FormField
            control={form.control}
            name="price"
            render={({ field }) => (
              <FormItem className="w-20 space-y-0">
                <FormControl>
                  <Input {...field} type="number" step="0.01" className="h-8 text-xs px-1 text-right bg-background" placeholder="Cena" />
                </FormControl>
              </FormItem>
            )}
          />

          {/* Akcje */}
          <div className="flex gap-1 shrink-0">
            <Button type="submit" size="icon" variant="default" className="h-8 w-8" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            </Button>
            <Button type="button" size="icon" variant="ghost" className="h-8 w-8 hover:bg-destructive/10 hover:text-destructive" onClick={() => setIsEditing(false)}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
