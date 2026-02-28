import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Category } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lock, Trash2, Edit2, Plus, ChevronRight, ChevronDown, Save, X, GripVertical, ArrowUp, ArrowDown } from "lucide-react";
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
} from "@/components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import type { DropResult } from "@hello-pangea/dnd";

export function CategoriesTab() {
  const queryClient = useQueryClient();
  const { data: serverCategories, isLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const [categories, setCategories] = useState<Category[]>([]);
  
  useEffect(() => {
    if (serverCategories) {
      // Sort by order_index, fallback to ID to ensure stable sort
      const sorted = [...serverCategories].sort((a, b) => {
        const orderA = a.order_index ?? 0;
        const orderB = b.order_index ?? 0;
        return orderA - orderB || a.id - b.id;
      });
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCategories(sorted);
    }
  }, [serverCategories]);

  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");
  const [editIcon, setEditIcon] = useState("");

  const [newCatParentId, setNewCatParentId] = useState<number | null>(null);
  const [newCatName, setNewCatName] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  const [deleteCatId, setDeleteCatId] = useState<number | null>(null);
  const [reassignTo, setReassignTo] = useState<string>("parent");

  const toggleExpand = (id: number) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const createMutation = useMutation({
    mutationFn: (data: Partial<Category>) => api.createCategory(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setIsAdding(false);
      setNewCatParentId(null);
      setNewCatName("");
      toast.success("Kategoria dodana");
    },
    onError: () => toast.error("Błąd dodawania kategorii"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Category> }) => api.updateCategory(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setEditingId(null);
      toast.success("Zapisano");
    },
    onError: () => toast.error("Błąd podczas zapisu"),
  });

  const reorderMutation = useMutation({
    mutationFn: async (updates: { id: number; order_index: number }[]) => {
      // Execute sequentially or in parallel
      await Promise.all(updates.map(u => api.updateCategory(u.id, { order_index: u.order_index })));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, reassign }: { id: number; reassign?: number }) => api.deleteCategory(id, reassign),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setDeleteCatId(null);
      toast.success("Kategoria usunięta");
    },
    onError: () => toast.error("Nie udało się usunąć kategorii"),
  });

  if (isLoading) return <div className="p-4">Ładowanie kategorii...</div>;

  const parents = categories.filter(c => !c.parent_id);
  const getChildren = (parentId: number) => categories.filter(c => c.parent_id === parentId);

  const handleStartEdit = (cat: Category) => {
    setEditingId(cat.id);
    setEditName(cat.name);
    setEditColor(cat.color || "#cccccc");
    setEditIcon(cat.icon || "📦");
  };

  const handleSaveEdit = (id: number) => {
    updateMutation.mutate({
      id,
      data: { name: editName, color: editColor, icon: editIcon }
    });
  };

  const handleDelete = () => {
    if (!deleteCatId) return;
    const target = reassignTo === "parent" || reassignTo === "none" ? undefined : parseInt(reassignTo);
    deleteMutation.mutate({ id: deleteCatId, reassign: target });
  };

  const handleMove = (id: number, direction: 'up' | 'down') => {
    const catToMove = categories.find(c => c.id === id);
    if (!catToMove) return;

    const siblings = categories.filter(c => c.parent_id === catToMove.parent_id);
    const index = siblings.findIndex(c => c.id === id);
    
    if (direction === 'up' && index > 0) {
      const prev = siblings[index - 1];
      reorderMutation.mutate([
        { id: catToMove.id, order_index: prev.order_index ?? index - 1 },
        { id: prev.id, order_index: catToMove.order_index ?? index }
      ]);
    } else if (direction === 'down' && index < siblings.length - 1) {
      const next = siblings[index + 1];
      reorderMutation.mutate([
        { id: catToMove.id, order_index: next.order_index ?? index + 1 },
        { id: next.id, order_index: catToMove.order_index ?? index }
      ]);
    }
  };

  const onDragEnd = (result: DropResult) => {
    if (!result.destination) return;
    
    const sourceIndex = result.source.index;
    const destIndex = result.destination.index;
    const listId = result.source.droppableId; // e.g. "root" or "children-5"

    if (sourceIndex === destIndex) return;

    // Determine siblings based on drop zone
    let siblings: Category[];
    if (listId === "root") {
      siblings = [...parents];
    } else {
      const parentId = parseInt(listId.replace("children-", ""));
      siblings = [...getChildren(parentId)];
    }

    // Reorder array
    const [movedItem] = siblings.splice(sourceIndex, 1);
    siblings.splice(destIndex, 0, movedItem);

    // Optimistic UI update
    setCategories(prev => {
      const nonSiblings = prev.filter(c => c.parent_id !== movedItem.parent_id);
      return [...nonSiblings, ...siblings].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
    });

    // Send updates to backend
    const updates = siblings.map((cat, idx) => ({
      id: cat.id,
      order_index: idx
    }));
    reorderMutation.mutate(updates);
  };

  const renderCategoryRow = (cat: Category, level: number = 0, index: number, isLast: boolean) => {
    const children = getChildren(cat.id);
    const hasChildren = children.length > 0;
    const isExpanded = expanded[cat.id];
    const isEditing = editingId === cat.id;

    return (
      <Draggable key={cat.id} draggableId={cat.id.toString()} index={index}>
        {(provided, snapshot) => (
          <div 
            ref={provided.innerRef}
            {...provided.draggableProps}
            style={{
               ...provided.draggableProps.style,
               opacity: snapshot.isDragging ? 0.8 : 1,
            }}
            className={`border-b border-border/40 ${snapshot.isDragging ? 'bg-muted shadow-lg z-50 rounded-lg' : ''}`}
          >
            <div className={`flex items-center justify-between p-3 transition-colors ${level > 0 ? 'pl-10 bg-muted/10 hover:bg-muted/30' : 'bg-card hover:bg-muted/50'}`}>
              <div className="flex items-center gap-3 flex-1">
                {/* Drag Handle (Desktop) */}
                <div 
                  className="hidden md:flex text-muted-foreground/50 hover:text-foreground cursor-grab active:cursor-grabbing p-1 -ml-1 rounded"
                  {...provided.dragHandleProps}
                >
                  <GripVertical className="h-4 w-4" />
                </div>
                
                {/* Arrows (Mobile) */}
                <div className="flex flex-col md:hidden text-muted-foreground mr-1">
                  <button disabled={index === 0} onClick={() => handleMove(cat.id, 'up')} className="disabled:opacity-20 p-1">
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <button disabled={isLast} onClick={() => handleMove(cat.id, 'down')} className="disabled:opacity-20 p-1">
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {level === 0 && (
                  <button 
                    onClick={() => toggleExpand(cat.id)}
                    className="w-6 h-6 flex items-center justify-center text-muted-foreground hover:text-foreground shrink-0"
                  >
                    {hasChildren ? (isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />) : <div className="w-4" />}
                  </button>
                )}
                
                {isEditing ? (
                  <div className="flex items-center gap-2 flex-1 max-w-[300px]">
                    <Input 
                      value={editIcon} 
                      onChange={e => setEditIcon(e.target.value)} 
                      className="w-12 h-8 text-center p-1"
                      maxLength={2}
                    />
                    <Input 
                      value={editName} 
                      onChange={e => setEditName(e.target.value)} 
                      className="flex-1 h-8"
                    />
                    <input 
                      type="color" 
                      value={editColor} 
                      onChange={e => setEditColor(e.target.value)}
                      className="w-8 h-8 rounded border-0 cursor-pointer shrink-0"
                    />
                    <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => handleSaveEdit(cat.id)}>
                      <Save className="h-4 w-4 text-emerald-600" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => setEditingId(null)}>
                      <X className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                ) : (
                  <div 
                    className="flex items-center gap-3 flex-1 cursor-pointer"
                    onDoubleClick={() => handleStartEdit(cat)}
                  >
                    <div 
                      className="w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-white text-sm shadow-sm"
                      style={{ backgroundColor: cat.color || "#9ca3af" }}
                    >
                      {cat.icon || "📦"}
                    </div>
                    <span className="font-medium truncate">{cat.name}</span>
                    {cat.is_system && <div title="Kategoria systemowa"><Lock className="h-3 w-3 text-muted-foreground ml-1 shrink-0" /></div>}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                  {level === 0 && !cat.is_system && (
                    <Button 
                      size="sm" 
                      variant="ghost" 
                      className="text-xs text-muted-foreground h-8 hidden sm:flex"
                      onClick={() => {
                        setNewCatParentId(cat.id);
                        setIsAdding(true);
                      }}
                    >
                      <Plus className="h-3 w-3 mr-1" /> Podkategoria
                    </Button>
                  )}
                  {!cat.is_system && (
                    <>
                      <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => handleStartEdit(cat)}>
                        <Edit2 className="h-3 w-3" />
                      </Button>
                      <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10" onClick={() => setDeleteCatId(cat.id)}>
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Subcategories */}
            {isExpanded && hasChildren && (
              <Droppable droppableId={`children-${cat.id}`} type={`subcategory-${cat.id}`}>
                {(providedChild) => (
                  <div 
                    className="border-l-2 border-primary/20 ml-[3.25rem]"
                    ref={providedChild.innerRef}
                    {...providedChild.droppableProps}
                  >
                    {children.map((child, childIdx) => renderCategoryRow(child, level + 1, childIdx, childIdx === children.length - 1))}
                    {providedChild.placeholder}
                  </div>
                )}
              </Droppable>
            )}
          </div>
        )}
      </Draggable>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-lg font-medium">Struktura kategorii</h3>
        <Button onClick={() => {
          setNewCatParentId(null);
          setIsAdding(true);
        }}>
          <Plus className="h-4 w-4 mr-2" /> Dodaj kategorię
        </Button>
      </div>

      <div className="bg-card rounded-xl border shadow-sm overflow-hidden group">
        <DragDropContext onDragEnd={onDragEnd}>
          <Droppable droppableId="root" type="parent">
            {(provided) => (
              <div 
                ref={provided.innerRef} 
                {...provided.droppableProps}
                className="min-h-[100px]"
              >
                {parents.length === 0 && !isLoading ? (
                  <div className="p-8 text-center text-muted-foreground">
                    Brak kategorii. Stwórz swoją pierwszą kategorię!
                  </div>
                ) : (
                  parents.map((cat, idx) => renderCategoryRow(cat, 0, idx, idx === parents.length - 1))
                )}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>
      </div>

      {isAdding && (
        <div className="bg-card p-4 rounded-xl border shadow-sm flex flex-col sm:flex-row items-center gap-3">
          <Input 
            placeholder={newCatParentId ? "Wpisz nazwę podkategorii..." : "Wpisz nazwę kategorii..."} 
            value={newCatName}
            onChange={e => setNewCatName(e.target.value)}
            className="flex-1"
            autoFocus
          />
          <div className="flex gap-2 w-full sm:w-auto">
            <Button className="flex-1 sm:flex-none" disabled={!newCatName.trim()} onClick={() => createMutation.mutate({ name: newCatName.trim(), parent_id: newCatParentId || undefined })}>
              Zapisz
            </Button>
            <Button variant="ghost" onClick={() => setIsAdding(false)}>Anuluj</Button>
          </div>
        </div>
      )}

      {/* Delete Dialog */}
      <AlertDialog open={!!deleteCatId} onOpenChange={(open) => !open && setDeleteCatId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Usunąć kategorię?</AlertDialogTitle>
            <AlertDialogDescription>
              Wybierz co zrobić z przypisanymi do niej transakcjami.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-4">
            <Select value={reassignTo} onValueChange={setReassignTo}>
              <SelectTrigger>
                <SelectValue placeholder="Wybierz akcję" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="parent">Przenieś do kategorii nadrzędnej (jeśli istnieje)</SelectItem>
                <SelectItem value="none">Oznacz jako Bez Kategorii</SelectItem>
                {parents.filter(p => p.id !== deleteCatId).map(p => (
                  <SelectItem key={p.id} value={p.id.toString()}>
                    Przenieś do: {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Anuluj</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">
              Potwierdź usunięcie
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}