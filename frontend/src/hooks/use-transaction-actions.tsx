import { useState, useEffect } from "react";
import { useScanReceipt } from "./use-scan-receipt";
import { useAddTransaction } from "./use-add-transaction";
import { QuickEntryDrawer } from "@/components/QuickEntryDrawer";
import { AddTransactionModal } from "@/components/dashboard/AddTransactionModal";

export function useTransactionActions() {
  const [quickEntryOpen, setQuickEntryOpen] = useState(false);
  const { isAddTxOpen, setIsAddTxOpen, openAddTransaction } = useAddTransaction();
  const { scanReceipt, isScanning } = useScanReceipt();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "n" || e.key === "N") {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        setQuickEntryOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const renderModals = () => (
    <>
      <QuickEntryDrawer
        open={quickEntryOpen}
        onOpenChange={setQuickEntryOpen}
        onScanReceipt={scanReceipt}
        onManualEntry={openAddTransaction}
        scanPending={isScanning}
      />
      <AddTransactionModal
        open={isAddTxOpen}
        onOpenChange={setIsAddTxOpen}
      />
    </>
  );

  return {
    quickEntryOpen,
    setQuickEntryOpen,
    openAddTransaction,
    scanReceipt,
    isScanning,
    renderModals,
  };
}
