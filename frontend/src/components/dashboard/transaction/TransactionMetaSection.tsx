import type { Control } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { SectionGrid } from "../shared/SectionGrid";
import type { TransactionFormInput } from "./schema";

interface TransactionMetaSectionProps {
  control: Control<TransactionFormInput>;
}

export function TransactionMetaSection({ control }: TransactionMetaSectionProps) {
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  return (
    <SectionGrid>
      <FormField
        control={control}
        name="category_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Kategoria
            </FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder="Wybierz kategorię" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {categories?.map((cat) => (
                  <SelectItem key={cat.id} value={cat.id.toString()}>
                    <span className="flex items-center gap-2">
                      <span className="w-4 text-center">{cat.icon}</span>
                      {cat.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="note"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Opis (opcjonalnie)
            </FormLabel>
            <FormControl>
              <Input placeholder="np. tygodniowe zakupy" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </SectionGrid>
  );
}
