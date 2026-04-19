import { useState } from "react";

export function useAddTransaction() {
  const [isOpen, setIsOpen] = useState(false);

  const openAddTransaction = () => setIsOpen(true);
  const closeAddTransaction = () => setIsOpen(false);

  return {
    isAddTxOpen: isOpen,
    setIsAddTxOpen: setIsOpen,
    openAddTransaction,
    closeAddTransaction,
  };
}
