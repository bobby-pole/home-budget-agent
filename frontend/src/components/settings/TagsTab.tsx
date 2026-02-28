import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tag as TagIcon, X, Plus, Save } from "lucide-react";
import { toast } from "sonner";
import { TAG_COLORS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  const [newTagColor, setNewTagColor] = useState(TAG_COLORS[0]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

  const { data: tags, isLoading } = useQuery({
    queryKey: ["tags"],
    queryFn: api.getTags,
  });

  const createMutation = useMutation({
    mutationFn: (data: { name: string; color: string }) => api.createTag(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      setNewTag("");
      setNewTagColor("#9ca3af");
      toast.success("Tag został dodany");
    },
    onError: () => toast.error("Nie udało się dodać tagu"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name?: string; color?: string } }) => api.updateTag(id, data),
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
      createMutation.mutate({ name: newTag.trim(), color: newTagColor });
    }
  };

  const handleSaveEdit = (id: number) => {
    if (editName.trim()) {
      updateMutation.mutate({ id, data: { name: editName.trim(), color: editColor } });
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
        
        <form onSubmit={handleAddTag} className="flex flex-wrap gap-2 mb-6">
          <Input 
            placeholder="Dodaj nowy tag (np. #wakacje2026)" 
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            className="max-w-sm h-9"
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" className="h-9 w-9 shrink-0 p-0" title="Wybierz kolor">
                <div 
                  className="w-5 h-5 rounded-full shadow-sm border border-black/10" 
                  style={{ backgroundColor: newTagColor }} 
                />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="p-2">
              <div className="grid grid-cols-5 gap-2">
                {TAG_COLORS.map(color => (
                  <button
                    key={color}
                    type="button"
                    className={cn(
                      "w-6 h-6 rounded-full border border-black/10 transition-transform hover:scale-110",
                      newTagColor === color && "ring-2 ring-ring ring-offset-1"
                    )}
                    style={{ backgroundColor: color }}
                    onClick={() => setNewTagColor(color)}
                  />
                ))}
              </div>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button type="submit" className="h-9" disabled={!newTag.trim() || createMutation.isPending}>
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
                <div key={tag.id} className="flex items-center gap-1 bg-secondary p-1 rounded-md border shadow-sm animate-in zoom-in-95 duration-200">
                  <span className="text-muted-foreground ml-1 text-sm font-bold">#</span>
                  <input
                    autoFocus
                    className="bg-transparent border-b border-primary/50 outline-none w-24 text-sm py-0.5 px-1 font-medium"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, tag.id)}
                  />
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="w-5 h-5 rounded-full border border-black/10 shadow-sm shrink-0 transition-transform hover:scale-110" style={{ backgroundColor: editColor }} />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="center" className="p-2">
                      <div className="grid grid-cols-5 gap-2">
                        {TAG_COLORS.map(color => (
                          <button
                            key={color}
                            type="button"
                            className={cn(
                              "w-5 h-5 rounded-full border border-black/10 transition-transform hover:scale-110",
                              editColor === color && "ring-2 ring-ring ring-offset-1"
                            )}
                            style={{ backgroundColor: color }}
                            onClick={() => setEditColor(color)}
                          />
                        ))}
                      </div>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => handleSaveEdit(tag.id)}>
                    <Save className="h-3 w-3 text-emerald-600" />
                  </Button>
                  <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => setEditingId(null)}>
                    <X className="h-3 w-3 text-destructive" />
                  </Button>
                </div>
              ) : (
                <Badge 
                  key={tag.id} 
                  variant="secondary" 
                  className="px-3 py-1.5 text-sm group flex items-center gap-1.5 transition-all text-white border-0 shadow-sm"
                  style={{ backgroundColor: tag.color || "#9ca3af" }}
                >
                  <span 
                    className="cursor-pointer hover:underline underline-offset-2"
                    onClick={() => {
                      setEditingId(tag.id);
                      setEditName(tag.name);
                      setEditColor(tag.color || "#9ca3af");
                    }}
                  >
                    #{tag.name}
                  </span>
                  
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button className="text-white/70 hover:text-white transition-colors focus:outline-none ml-1">
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