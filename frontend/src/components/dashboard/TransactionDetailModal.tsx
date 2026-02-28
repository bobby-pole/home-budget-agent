import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Transaction } from "@/types";
import { TransactionHeaderForm } from "./transaction/TransactionHeaderForm";
import { TransactionItemsSection } from "./transaction/TransactionItemsSection";

interface TransactionDetailModalProps {
  transaction: Transaction | null;
  isOpen: boolean;
  onClose: () => void;
}

export function TransactionDetailModal({ transaction, isOpen, onClose }: TransactionDetailModalProps) {
  if (!transaction) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[650px] max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-2 border-b mb-4">
          <DialogTitle>Szczegóły transakcji #{transaction.id}</DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-1 space-y-6">
          <TransactionHeaderForm transaction={transaction} />
          <TransactionItemsSection lines={transaction.lines} currency={transaction.currency} transactionId={transaction.id} />
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
