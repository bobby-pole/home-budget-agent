import type { Control } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
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
import { Textarea } from "@/components/ui/textarea";
import { SectionGrid } from "../shared/SectionGrid";
import type { TransactionFormInput } from "./schema";
import { CATEGORY_LABELS } from "@/lib/constants";
import { TagPicker } from "../shared/TagPicker";
import { useWatch } from "react-hook-form";

interface TransactionMetaSectionProps {
  control: Control<TransactionFormInput>;
  hideCategory?: boolean;
}

export function TransactionMetaSection({ control, hideCategory = false }: TransactionMetaSectionProps) {
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const transactionType = useWatch({ control, name: "type", defaultValue: "expense" });

  return (
    <SectionGrid>
      <FormField
        control={control}
        name="account_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              {t("transactions.meta_section.account_label")}
            </FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder={t("transactions.meta_section.account_placeholder")} />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {accounts?.map((acc) => (
                  <SelectItem key={acc.id} value={acc.id.toString()}>
                    {acc.name} ({acc.currency})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      {transactionType === "transfer" && (
        <FormField
          control={control}
          name="transfer_id"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                {t("transactions.meta_section.transfer_label")}
              </FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder={t("transactions.meta_section.transfer_placeholder")} />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {accounts?.map((acc) => (
                    <SelectItem key={acc.id} value={acc.id.toString()}>
                      {acc.name} ({acc.currency})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      )}

      {!hideCategory && transactionType !== "transfer" && (
        <FormField
          control={control}
          name="category_id"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
                {t("transactions.meta_section.category_label")}
              </FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder={t("transactions.meta_section.category_placeholder")} />
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
      )}

      <FormField
        control={control}
        name="note"
        render={({ field }) => (
          <FormItem className="col-span-full">
            <FormLabel className="text-xs font-semibold uppercase text-muted-foreground">
              {t("transactions.meta_section.note_label")}
            </FormLabel>
            <FormControl>
              <Textarea
                placeholder={t("transactions.meta_section.placeholder_note")}
                className="resize-none"
                rows={2}
                {...field}
              />
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
              {t("transactions.meta_section.tags_label")}
            </FormLabel>
            <TagPicker value={field.value || []} onChange={field.onChange} />
            <FormMessage />
          </FormItem>
        )}
      />
    </SectionGrid>
  );
}
