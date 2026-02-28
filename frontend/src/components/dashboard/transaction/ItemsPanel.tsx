import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { ItemRow } from "./ItemRow";
import { DraftItemRow } from "./DraftItemRow";
import type { ManualItem } from "./ItemRow";
import type { NewItemDraft } from "./DraftItemRow";

export type { ManualItem, NewItemDraft };

const EMPTY_DRAFT: NewItemDraft = {
  name: "",
  price: "",
  quantity: "1",
  category_id: null,
};

interface ItemsPanelProps {
  items: ManualItem[];
  currency: string;
  onItemsChange: (items: ManualItem[]) => void;
}

export function ItemsPanel({ items, currency, onItemsChange }: ItemsPanelProps) {
  const [draft, setDraft] = useState<NewItemDraft | null>(null);
  const draftNameRef = useRef<HTMLInputElement>(null);

  const draftValid = !!(draft?.name.trim() && draft?.price);

  const confirmDraft = () => {
    if (!draft?.name.trim() || !draft.price) return;
    const price = parseFloat(draft.price);
    const quantity = parseFloat(draft.quantity) || 1;
    if (isNaN(price) || price <= 0) return;
    onItemsChange([
      ...items,
      {
        id: crypto.randomUUID(),
        name: draft.name.trim(),
        price,
        quantity,
        category_id: draft.category_id,
      },
    ]);
    setDraft(null);
  };

  const handleDraftKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      confirmDraft();
    }
    if (e.key === "Escape") setDraft(null);
  };

  return (
    <div className="border rounded-lg bg-muted/20 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b bg-muted/10">
        <span className="text-xs font-semibold uppercase text-muted-foreground flex items-center gap-2">
          Pozycje
          {items.length > 0 && (
            <span className="bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[10px] font-bold">
              {items.length}
            </span>
          )}
        </span>
        {!draft && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={() => {
              setDraft({ ...EMPTY_DRAFT });
              setTimeout(() => draftNameRef.current?.focus(), 50);
            }}
          >
            <Plus className="h-3 w-3" />
            Dodaj pozycję
          </Button>
        )}
      </div>

      {items.length > 0 && (
        <div className="divide-y">
          {items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              currency={currency}
              onRemove={(id) => onItemsChange(items.filter((i) => i.id !== id))}
            />
          ))}
        </div>
      )}

      {draft !== null && (
        <DraftItemRow
          draft={draft}
          draftNameRef={draftNameRef}
          draftValid={draftValid}
          onChange={(newDraft) => setDraft(newDraft)}
          onConfirm={confirmDraft}
          onCancel={() => setDraft(null)}
          onKeyDown={handleDraftKeyDown}
        />
      )}

      {items.length === 0 && !draft && (
        <p className="px-4 py-3 text-xs text-muted-foreground">
          Brak pozycji — paragon zostanie zapisany jako całość z podaną kwotą.
        </p>
      )}
    </div>
  );
}
