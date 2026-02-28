import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Plus, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface TagPickerProps {
  value: number[];
  onChange: (newValue: number[]) => void;
  disabled?: boolean;
}

export function TagPicker({ value, onChange, disabled }: TagPickerProps) {
  const queryClient = useQueryClient();
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#9ca3af");

  const { data: tags } = useQuery({
    queryKey: ["tags"],
    queryFn: api.getTags,
  });

  const createTagMutation = useMutation({
    mutationFn: (data: { name: string; color: string }) => api.createTag(data),
    onSuccess: (newTag) => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      setNewTagName("");
      setNewTagColor("#9ca3af");
      // Automatically select the newly created tag
      onChange([...(value || []), newTag.id]);
      toast.success(`Utworzono tag #${newTag.name}`);
    },
    onError: () => toast.error("Nie udało się utworzyć tagu"),
  });

  const handleCreateTag = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.preventDefault();
    if (!newTagName.trim() || disabled) return;
    
    // Check if tag already exists in the list of all user tags
    const existing = tags?.find(t => t.name.toLowerCase() === newTagName.trim().toLowerCase());
    if (existing) {
      if (!value?.includes(existing.id)) {
        onChange([...(value || []), existing.id]);
      }
      setNewTagName("");
      return;
    }

    createTagMutation.mutate({ name: newTagName.trim(), color: newTagColor });
  };

  return (
    <div className="space-y-3 w-full">
      <div className="flex gap-2">
        <div className="relative flex-1 max-w-[200px] flex gap-2">
          <Input
            placeholder="Nowy tag..."
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateTag(e)}
            disabled={disabled || createTagMutation.isPending}
            className="h-8 text-xs flex-1"
          />
          <input 
            type="color" 
            value={newTagColor} 
            onChange={e => setNewTagColor(e.target.value)}
            className="w-8 h-8 rounded border border-input cursor-pointer p-0.5 shrink-0"
            title="Wybierz kolor tagu"
            disabled={disabled || createTagMutation.isPending}
          />
          <button
            type="button"
            onClick={handleCreateTag}
            disabled={disabled || !newTagName.trim() || createTagMutation.isPending}
            className="flex items-center justify-center w-8 h-8 rounded-md bg-secondary text-muted-foreground hover:text-primary disabled:opacity-30 border border-input shrink-0"
          >
            {createTagMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {tags?.map((tag) => {
          const isSelected = value?.includes(tag.id);
          const color = tag.color || "#9ca3af";
          
          return (
            <Badge
              key={tag.id}
              variant={isSelected ? "default" : "outline"}
              className={cn(
                "transition-all border-0 shadow-sm",
                !disabled && "cursor-pointer hover:opacity-80",
                !isSelected && "bg-muted text-muted-foreground",
                isSelected && "text-white font-semibold",
                disabled && !isSelected && "opacity-50"
              )}
              style={{ backgroundColor: isSelected ? color : undefined }}
              onClick={() => {
                if (disabled) return;
                const newValue = isSelected
                  ? value?.filter((id: number) => id !== tag.id)
                  : [...(value || []), tag.id];
                onChange(newValue);
              }}
            >
              #{tag.name}
            </Badge>
          );
        })}
        {(!tags || tags.length === 0) && !createTagMutation.isPending && (
          <p className="text-xs text-muted-foreground italic">
            Brak tagów. Wpisz nazwę powyżej, aby dodać pierwszy!
          </p>
        )}
      </div>
    </div>
  );
}
