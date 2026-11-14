import * as z from "zod";
import { t } from "@/lib/i18n";
import { isPositiveMoneyInput, parseMoneyInput } from "@/lib/money";

export const transactionSchema = z.object({
  merchant_name: z.string().min(1, t("transactions.add_modal.validation.required")),
  total_amount: z
    .union([z.string(), z.number()])
    .optional()
    .transform((val) => {
      if (val === undefined || val === "") return undefined;
      return String(val);
    })
    .refine(
      (val) => val === undefined || isPositiveMoneyInput(val),
      t("transactions.add_modal.validation.positive"),
    )
    .transform((val) => (val === undefined ? undefined : (parseMoneyInput(val) ?? val))),
  currency: z.string().min(1),
  date: z.string().optional(),
  category_id: z.string().optional(),
  account_id: z.string().min(1, t("transactions.add_modal.validation.account_required")),
  transfer_id: z.string().optional(),
  note: z.string().optional(),
  tag_ids: z.array(z.number()).default([]),
  type: z.enum(["expense", "income", "transfer"]).default("expense"),
}).superRefine((data, ctx) => {
  if (data.type === "transfer") {
    if (!data.transfer_id) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: t("transactions.add_modal.validation.transfer_destination_required"),
        path: ["transfer_id"],
      });
    } else if (data.transfer_id === data.account_id) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: t("transactions.add_modal.validation.transfer_same_account"),
        path: ["transfer_id"],
      });
    }
  }
});

export type TransactionFormInput = z.input<typeof transactionSchema>;
export type TransactionFormValues = z.output<typeof transactionSchema>;
