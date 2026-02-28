import * as z from "zod";

export const transactionSchema = z.object({
  merchant_name: z.string().min(1, "Wymagane"),
  total_amount: z.coerce.number().positive("Musi być większe od 0").optional(),
  currency: z.string().min(1),
  date: z.string().optional(),
  category: z.string().optional(),
  note: z.string().optional(),
});

export type TransactionFormInput = z.input<typeof transactionSchema>;
export type TransactionFormValues = z.output<typeof transactionSchema>;
