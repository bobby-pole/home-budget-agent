import type { Control } from "react-hook-form";
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
import { CATEGORIES, CATEGORY_LABELS } from "@/lib/constants";
import { SectionGrid } from "../shared/SectionGrid";
import type { TransactionFormInput } from "./schema";

interface TransactionMetaSectionProps {
  control: Control<TransactionFormInput>;
}

export function TransactionMetaSection({ control }: TransactionMetaSectionProps) {
  return (
    <SectionGrid>
      <FormField
        control={control}
        name="category"
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
                {CATEGORIES.map((cat) => (
                  <SelectItem key={cat} value={cat}>
                    {CATEGORY_LABELS[cat] || cat}
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
