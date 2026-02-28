import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Check, X } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CATEGORIES, CATEGORY_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";

export interface NewItemDraft {
  name: string;
  price: string;
  quantity: string;
  category: string;
}

interface DraftItemRowProps {
  draft: NewItemDraft;
  draftNameRef: React.RefObject<HTMLInputElement | null>;
  draftValid: boolean;
  onChange: (draft: NewItemDraft) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

export function DraftItemRow({
  draft,
  draftNameRef,
  draftValid,
  onChange,
  onConfirm,
  onCancel,
  onKeyDown,
}: DraftItemRowProps) {
  return (
    <div
      className="flex items-center gap-2 px-4 py-2 bg-background border-t"
      onKeyDown={onKeyDown}
    >
      <Input
        ref={draftNameRef}
        placeholder="Nazwa pozycji"
        value={draft.name}
        onChange={(e) => onChange({ ...draft, name: e.target.value })}
        className="flex-1 h-8 text-xs min-w-0"
      />
      <Input
        type="number"
        step="0.01"
        min="0.01"
        placeholder="Cena"
        value={draft.price}
        onChange={(e) => onChange({ ...draft, price: e.target.value })}
        className="w-20 h-8 text-xs shrink-0"
      />
      <Input
        type="number"
        step="0.1"
        min="0.1"
        placeholder="Ilość"
        value={draft.quantity}
        onChange={(e) => onChange({ ...draft, quantity: e.target.value })}
        className="w-16 h-8 text-xs shrink-0"
      />
      <Select
        value={draft.category}
        onValueChange={(cat) => onChange({ ...draft, category: cat })}
      >
        <SelectTrigger className="w-28 h-8 text-xs shrink-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CATEGORIES.map((cat) => (
            <SelectItem key={cat} value={cat}>
              {CATEGORY_LABELS[cat] || cat}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        type="button"
        size="icon"
        className={cn("h-8 w-8 shrink-0", !draftValid && "opacity-40 cursor-not-allowed")}
        onClick={onConfirm}
        disabled={!draftValid}
      >
        <Check className="h-3.5 w-3.5" />
      </Button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="h-8 w-8 shrink-0 hover:text-destructive"
        onClick={onCancel}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
