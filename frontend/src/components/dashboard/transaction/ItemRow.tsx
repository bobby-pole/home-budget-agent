import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/constants";

export interface ManualItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
  category: string;
}

interface ItemRowProps {
  item: ManualItem;
  currency: string;
  onRemove: (id: string) => void;
}

export function ItemRow({ item, currency, onRemove }: ItemRowProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-muted/30 transition-colors">
      <span className="flex-1 font-medium truncate min-w-0" title={item.name}>
        {item.name}
      </span>
      <span className="text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
        {CATEGORY_LABELS[item.category] || item.category}
      </span>
      <span className="text-muted-foreground text-xs shrink-0 w-14 text-right">
        {item.quantity} szt.
      </span>
      <span className="font-semibold shrink-0 w-24 text-right tabular-nums">
        {(item.price * item.quantity).toFixed(2)} {currency}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0"
        onClick={() => onRemove(item.id)}
      >
        <Trash2 className="h-3 w-3" />
      </Button>
    </div>
  );
}
