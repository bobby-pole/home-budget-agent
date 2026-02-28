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
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/constants";

export interface NewItemDraft {
  name: string;
  price: string;
  quantity: string;
  category_id: number | null;
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
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

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
        value={draft.category_id != null ? String(draft.category_id) : ""}
        onValueChange={(val) => onChange({ ...draft, category_id: val ? parseInt(val) : null })}
      >
        <SelectTrigger className="w-32 h-8 text-xs shrink-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {categories?.map((cat) => (
            <SelectItem key={cat.id} value={String(cat.id)}>
              <span className="flex items-center gap-2">
                <span>{cat.icon}</span>
                {cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name}
              </span>
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
