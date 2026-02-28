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
import { CATEGORY_LABELS } from "@/lib/constants";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface TransactionMetaSectionProps {
  control: Control<TransactionFormInput>;
}

export function TransactionMetaSection({ control }: TransactionMetaSectionProps) {
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const { data: tags } = useQuery({
    queryKey: ["tags"],
    queryFn: api.getTags,
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
                      {cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name}
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

      <FormField
        control={control}
        name="tag_ids"
        render={({ field }) => (
          <FormItem className="col-span-full">
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Tagi
            </FormLabel>
            <div className="flex flex-wrap gap-2 pt-1">
              {tags?.map((tag) => {
                const isSelected = field.value?.includes(tag.id);
                return (
                  <Badge
                    key={tag.id}
                    variant={isSelected ? "default" : "outline"}
                    className={cn(
                      "cursor-pointer transition-all hover:opacity-80",
                      !isSelected && "text-muted-foreground"
                    )}
                    onClick={() => {
                      const newValue = isSelected
                        ? field.value?.filter((id: number) => id !== tag.id)
                        : [...(field.value || []), tag.id];
                      field.onChange(newValue);
                    }}
                  >
                    #{tag.name}
                  </Badge>
                );
              })}
              {(!tags || tags.length === 0) && (
                <p className="text-xs text-muted-foreground italic">
                  Brak zdefiniowanych tagów. Możesz je dodać w Ustawieniach.
                </p>
              )}
            </div>
            <FormMessage />
          </FormItem>
        )}
      />
    </SectionGrid>
  );
}
