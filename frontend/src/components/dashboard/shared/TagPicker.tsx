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

  const { data: tags } = useQuery({
    queryKey: ["tags"],
    queryFn: api.getTags,
  });

  const createTagMutation = useMutation({
    mutationFn: (name: string) => api.createTag({ name }),
    onSuccess: (newTag) => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      setNewTagName("");
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

    createTagMutation.mutate(newTagName.trim());
  };

  return (
    <div className="space-y-3 w-full">
      <div className="flex gap-2">
        <div className="relative flex-1 max-w-[200px]">
          <Input
            placeholder="Nowy tag..."
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateTag(e)}
            disabled={disabled || createTagMutation.isPending}
            className="h-8 text-xs pr-8"
          />
          <button
            type="button"
            onClick={handleCreateTag}
            disabled={disabled || !newTagName.trim() || createTagMutation.isPending}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-primary disabled:opacity-30"
          >
            {createTagMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {tags?.map((tag) => {
          const isSelected = value?.includes(tag.id);
          return (
            <Badge
              key={tag.id}
              variant={isSelected ? "default" : "outline"}
              className={cn(
                "transition-all",
                !disabled && "cursor-pointer hover:opacity-80",
                !isSelected && "text-muted-foreground",
                disabled && !isSelected && "opacity-50"
              )}
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
