import type { Control } from "react-hook-form";
import { useWatch } from "react-hook-form";
import { t } from "@/lib/i18n";
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
  const txType = useWatch({ control, name: "type" });
  const isIncome = txType === "income";

  return (
    <SectionGrid>
      <FormField
        control={control}
        name="merchant_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              {isIncome ? t("transactions.header_section.source_label") : t("transactions.header_section.merchant_label")}
            </FormLabel>
            <FormControl>
              <Input placeholder={isIncome ? t("transactions.header_section.placeholder_income") : t("transactions.header_section.placeholder_expense")} {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="type"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              {t("transactions.header_section.type_label")}
            </FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value="expense">{t("transactions.header_section.type_expense")}</SelectItem>
                <SelectItem value="income">{t("transactions.header_section.type_income")}</SelectItem>
                <SelectItem value="transfer">{t("transactions.header_section.type_transfer")}</SelectItem>
              </SelectContent>
            </Select>
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
              {t("transactions.header_section.date_label")}
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
                {t("transactions.header_section.amount_label")}
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
            {t("transactions.header_section.computed_total_label")}
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
              {t("transactions.header_section.currency_label")}
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
