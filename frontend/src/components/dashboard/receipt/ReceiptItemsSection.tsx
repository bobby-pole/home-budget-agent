import type { Receipt } from "@/types";
import { ReceiptItemRow } from "../ReceiptItemRow";

interface ReceiptItemsSectionProps {
  items: Receipt["items"];
  currency: string;
}

export function ReceiptItemsSection({ items, currency }: ReceiptItemsSectionProps) {
  return (
    <div>
      <h4 className="mb-3 text-sm font-semibold text-muted-foreground flex items-center gap-2">
        Pozycje na paragonie
        <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded-full text-xs">
          {items?.length || 0}
        </span>
      </h4>
      <div className="max-h-[350px] overflow-auto rounded-md border bg-card">
        {items?.length ? (
          <div className="divide-y min-w-max">
            {items.map((item) => (
              <ReceiptItemRow
                key={item.id}
                item={{ ...item, category: item.category ?? "Other" }}
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
