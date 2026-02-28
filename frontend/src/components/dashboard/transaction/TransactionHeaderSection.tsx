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
import { SectionGrid } from "../shared/SectionGrid";
import type { TransactionFormInput } from "./schema";

interface TransactionHeaderSectionProps {
  control: Control<TransactionFormInput>;
  hasItems: boolean;
  computedTotal: number;
  currency: string;
}

export function TransactionHeaderSection({
  control,
  hasItems,
  computedTotal,
  currency,
}: TransactionHeaderSectionProps) {
  return (
    <SectionGrid>
      <FormField
        control={control}
        name="merchant_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Sklep / Odbiorca
            </FormLabel>
            <FormControl>
              <Input placeholder="np. Biedronka" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="date"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Data
            </FormLabel>
            <FormControl>
              <Input type="date" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      {!hasItems ? (
        <FormField
          control={control}
          name="total_amount"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                Kwota
              </FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="0.01"
                  min="0.01"
                  placeholder="0.00"
                  {...field}
                  value={(field.value as number) ?? ""}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      ) : (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            Suma (wyliczona)
          </span>
          <div className="h-9 flex items-center px-3 rounded-md border bg-muted/40 text-sm font-bold text-primary">
            {computedTotal.toFixed(2)} {currency}
          </div>
        </div>
      )}

      <FormField
        control={control}
        name="currency"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              Waluta
            </FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value="PLN">PLN</SelectItem>
                <SelectItem value="EUR">EUR</SelectItem>
                <SelectItem value="USD">USD</SelectItem>
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />
    </SectionGrid>
  );
}
