import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tag as TagIcon, X, Plus } from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export function TagsTab() {
  const queryClient = useQueryClient();
  const [newTag, setNewTag] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  const { data: tags, isLoading } = useQuery({
    queryKey: ["tags"],
    queryFn: api.getTags,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => api.createTag({ name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      setNewTag("");
      toast.success("Tag został dodany");
    },
    onError: () => toast.error("Nie udało się dodać tagu"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => api.updateTag(id, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      setEditingId(null);
      toast.success("Zapisano");
    },
    onError: () => toast.error("Błąd podczas zapisu"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteTag(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      toast.success("Tag został usunięty");
    },
    onError: () => toast.error("Nie udało się usunąć tagu"),
  });

  const handleAddTag = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTag.trim()) {
      createMutation.mutate(newTag.trim());
    }
  };

  const handleSaveEdit = (id: number) => {
    if (editName.trim()) {
      updateMutation.mutate({ id, name: editName.trim() });
    } else {
      setEditingId(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, id: number) => {
    if (e.key === "Enter") handleSaveEdit(id);
    if (e.key === "Escape") setEditingId(null);
  };

  return (
    <div className="space-y-6">
      <div className="bg-card p-6 rounded-xl border shadow-sm">
        <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
          <TagIcon className="h-5 w-5 text-primary" />
          Twoje tagi
        </h3>
        
        <form onSubmit={handleAddTag} className="flex gap-2 mb-6">
          <Input 
            placeholder="Dodaj nowy tag (np. #wakacje2026)" 
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            className="max-w-sm"
          />
          <Button type="submit" disabled={!newTag.trim() || createMutation.isPending}>
            <Plus className="h-4 w-4 mr-2" /> Dodaj
          </Button>
        </form>

        {isLoading ? (
          <div className="flex gap-2 animate-pulse">
            <div className="h-8 w-20 bg-muted rounded-full"></div>
            <div className="h-8 w-24 bg-muted rounded-full"></div>
            <div className="h-8 w-16 bg-muted rounded-full"></div>
          </div>
        ) : tags?.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nie masz jeszcze żadnych tagów.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {tags?.map((tag) => (
              editingId === tag.id ? (
                <Badge key={tag.id} variant="secondary" className="px-1 py-0.5 text-sm flex items-center gap-1">
                  <span className="text-muted-foreground ml-1">#</span>
                  <input
                    autoFocus
                    className="bg-transparent border-b border-primary/50 outline-none w-20 text-sm py-0.5"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, tag.id)}
                    onBlur={() => handleSaveEdit(tag.id)}
                  />
                </Badge>
              ) : (
                <Badge key={tag.id} variant="secondary" className="px-3 py-1.5 text-sm group">
                  <span 
                    className="cursor-pointer hover:text-primary transition-colors"
                    onClick={() => {
                      setEditingId(tag.id);
                      setEditName(tag.name);
                    }}
                  >
                    #{tag.name}
                  </span>
                  
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button className="ml-2 text-muted-foreground hover:text-destructive transition-colors focus:outline-none">
                        <X className="h-3 w-3" />
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Usunąć tag?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Czy na pewno chcesz usunąć tag <strong>#{tag.name}</strong>? Ta akcja odepnie go od wszystkich transakcji i nie może być cofnięta.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Anuluj</AlertDialogCancel>
                        <AlertDialogAction 
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          onClick={() => deleteMutation.mutate(tag.id)}
                        >
                          Usuń tag
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </Badge>
              )
            ))}
          </div>
        )}
      </div>
    </div>
  );
}