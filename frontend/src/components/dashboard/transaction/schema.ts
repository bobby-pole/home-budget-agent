import * as z from "zod";
import { t } from "@/lib/i18n";

export const transactionSchema = z.object({
  merchant_name: z.string().min(1, t("transactions.add_modal.validation.required")),
  total_amount: z.coerce.number().positive(t("transactions.add_modal.validation.positive")).optional(),
  currency: z.string().min(1),
  date: z.string().optional(),
  category_id: z.string().optional(),
  note: z.string().optional(),
  tag_ids: z.array(z.number()).default([]),
  type: z.enum(["expense", "income", "transfer"]).default("expense"),
});

export type TransactionFormInput = z.input<typeof transactionSchema>;
export type TransactionFormValues = z.output<typeof transactionSchema>;
