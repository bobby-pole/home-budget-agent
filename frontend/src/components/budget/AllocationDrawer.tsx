import { useState } from "react";
import {
  Drawer,
  DrawerContent,
} from "@/components/ui/drawer";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, Save } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";

interface AllocationDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categoryId: number | null;
  categoryName: string;
  categoryIcon: string;
  currentPlanned: number;
  year: number;
  month: number;
}

export function AllocationDrawer({
  open,
  onOpenChange,
  categoryId,
  categoryName,
  categoryIcon,
  currentPlanned,
  year,
  month,
}: AllocationDrawerProps) {
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  const mutation = useMutation({
    mutationFn: (newAmount: number) => {
      if (!categoryId) throw new Error("No category selected");
      return api.setBudgetLimit(year, month, categoryId, newAmount);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      toast.success(`Zaktualizowano limit dla ${categoryName}`);
      onOpenChange(false);
    },
    onError: () => {
      toast.error("Błąd podczas zapisywania limitu");
    },
  });

  const formContent = (
    <div key={categoryId ?? 'none'}>
      <AllocationForm 
        categoryIcon={categoryIcon}
        categoryName={categoryName}
        currentPlanned={currentPlanned}
        onSave={(amount) => mutation.mutate(amount)}
        onCancel={() => onOpenChange(false)}
        isPending={mutation.isPending}
      />
    </div>
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange}>
        <DrawerContent className="rounded-t-[32px] max-h-[90vh]">
          <div className="mx-auto w-full max-w-sm p-6">
            {formContent}
          </div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden rounded-[32px] border-none shadow-2xl">
        <div className="p-6">
          {formContent}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AllocationForm({ 
  categoryIcon, 
  categoryName, 
  currentPlanned, 
  onSave, 
  onCancel,
  isPending 
}: { 
  categoryIcon: string; 
  categoryName: string; 
  currentPlanned: number; 
  onSave: (amount: number) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const [amount, setAmount] = useState<string>(currentPlanned > 0 ? currentPlanned.toString() : "");

  const handleSave = () => {
    const parsedAmount = parseFloat(amount.replace(",", "."));
    if (isNaN(parsedAmount) || parsedAmount < 0) {
      toast.error("Wprowadź poprawną kwotę");
      return;
    }
    onSave(parsedAmount);
  };

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div className="size-12 rounded-2xl bg-primary/10 flex items-center justify-center text-2xl shadow-inner shrink-0">
          {categoryIcon}
        </div>
        <div>
          <h2 className="text-2xl font-black tracking-tight leading-tight">{categoryName}</h2>
          <p className="text-xs font-medium text-muted-foreground">Ustaw limit wydatków</p>
        </div>
      </div>
      
      <div className="space-y-4 py-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="planned-amount" className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/70">
            Zaplanowana Kwota
          </Label>
          <div className="relative">
            <Input
              id="planned-amount"
              type="number"
              step="0.01"
              placeholder="0.00"
              className="text-3xl font-black h-16 rounded-2xl pr-16 bg-muted/30 border-muted focus:bg-background transition-colors"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSave();
              }}
              autoFocus
            />
            <div className="absolute right-5 top-1/2 -translate-y-1/2 text-lg text-muted-foreground font-black pointer-events-none">
              PLN
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3 mt-4">
        <Button 
          onClick={handleSave} 
          disabled={isPending}
          className="h-14 rounded-2xl font-black text-base shadow-lg shadow-primary/20 transition-all active:scale-95"
        >
          {isPending ? <Loader2 className="mr-2 size-5 animate-spin" /> : <Save className="mr-2 size-5" />}
          Zapisz limit
        </Button>
        <Button 
          variant="ghost" 
          onClick={onCancel}
          className="h-12 rounded-xl font-bold text-muted-foreground hover:text-foreground"
        >
          Anuluj
        </Button>
      </div>
    </>
  );
}
