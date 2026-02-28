import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Receipt } from "@/types";
import { ReceiptHeaderForm } from "./receipt/ReceiptHeaderForm";
import { ReceiptItemsSection } from "./receipt/ReceiptItemsSection";

interface ReceiptDetailModalProps {
  receipt: Receipt | null;
  isOpen: boolean;
  onClose: () => void;
}

export function ReceiptDetailModal({ receipt, isOpen, onClose }: ReceiptDetailModalProps) {
  if (!receipt) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[650px] max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-2 border-b mb-4">
          <DialogTitle>Szczegóły paragonu #{receipt.id}</DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-1 space-y-6">
          <ReceiptHeaderForm receipt={receipt} />
          <ReceiptItemsSection items={receipt.items} currency={receipt.currency} />
        </div>

        <DialogFooter className="mt-4 pt-2 border-t">
          <Button type="button" variant="secondary" onClick={onClose}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
