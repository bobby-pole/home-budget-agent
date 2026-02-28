import type { TransactionLine } from "@/types";
import { TransactionItemRow } from "../TransactionItemRow";

interface TransactionItemsSectionProps {
  lines: TransactionLine[];
  currency: string;
  transactionId: number;
}

export function TransactionItemsSection({ lines, currency, transactionId }: TransactionItemsSectionProps) {
  return (
    <div>
      <h4 className="mb-3 text-sm font-semibold text-muted-foreground flex items-center gap-2">
        Pozycje na paragonie
        <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded-full text-xs">
          {lines?.length || 0}
        </span>
      </h4>
      <div className="max-h-[350px] overflow-auto rounded-md border bg-card">
        {lines?.length ? (
          <div className="divide-y min-w-max">
            {lines.map((line) => (
              <TransactionItemRow
                key={line.id}
                item={line}
                transactionId={transactionId}
                currency={currency}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-[100px] text-muted-foreground text-sm p-4">
            <p>Brak wykrytych pozycji.</p>
          </div>
        )}
      </div>
    </div>
  );
}
