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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { CATEGORIES, CATEGORY_LABELS, CATEGORY_COLORS } from "@/lib/constants";
import { cn } from "@/lib/utils";

const itemSchema = z.object({
  name: z.string().min(1, "Nazwa wymagana"),
  price: z.coerce.number().min(0.01),
  quantity: z.coerce.number().min(0.1),
  category: z.string(),
});

interface ItemType {
  id: number;
  name: string;
  price: number;
  quantity: number;
  category: string;
}

interface ReceiptItemRowProps {
  item: ItemType;
  currency: string;
}

export function ReceiptItemRow({ item, currency }: ReceiptItemRowProps) {
  const [isEditing, setIsEditing] = useState(false);
  const queryClient = useQueryClient();

  const form = useForm<z.infer<typeof itemSchema>>({
    resolver: zodResolver(itemSchema),
    defaultValues: {
      name: item.name,
      price: item.price,
      quantity: item.quantity,
      category: item.category || "Other",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof itemSchema>) => 
      api.updateItem(item.id, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Zaktualizowano pozycję");
      setIsEditing(false);
    },
    onError: () => {
      toast.error("Błąd aktualizacji pozycji");
    },
  });

  const onSubmit = (values: z.infer<typeof itemSchema>) => {
    mutation.mutate(values);
  };

  if (!isEditing) {
    const badgeColor = CATEGORY_COLORS[item.category] || CATEGORY_COLORS["Other"];

    return (
      <div className="flex items-center justify-between py-2 px-2 text-sm border-b last:border-0 group h-[52px] hover:bg-muted/20 transition-colors min-w-[450px]">
        <div className="flex items-center flex-1 min-w-0 mr-2 gap-3">
          <span className="font-medium truncate shrink" title={item.name}>
            {item.name}
          </span>
          
          <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground ml-auto">
            <span className={cn("px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium", badgeColor)}>
                {CATEGORY_LABELS[item.category] || item.category}
            </span>
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
              name="category"
              render={({ field }) => (
                <FormItem className="w-28 space-y-0">
                  <FormControl>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                        <SelectTrigger className="h-8 text-xs px-2 bg-background">
                            <SelectValue placeholder="Kat." />
                        </SelectTrigger>
                        <SelectContent>
                            {CATEGORIES.map(cat => (
                                <SelectItem key={cat} value={cat}>
                                    {CATEGORY_LABELS[cat] || cat}
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
