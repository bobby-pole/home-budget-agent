import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { Store, RefreshCcw, Eye, Trash2 } from "lucide-react";
import type { Receipt } from "@/types";
import { cn } from "@/lib/utils";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ReceiptDetailModal } from "./ReceiptDetailModal";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "@/lib/constants";

const getReceiptCategory = (receipt: Receipt): string => {
  if (!receipt.items || receipt.items.length === 0) return "Other";
  const firstItemWithCategory = receipt.items.find((item) => item.category);
  return firstItemWithCategory?.category || "Other";
};

interface ReceiptsTableProps {
  receipts: Receipt[];
  isLoading?: boolean;
  error?: unknown;
}

export function ReceiptsTable({
  receipts,
  isLoading,
  error,
}: ReceiptsTableProps) {
  const queryClient = useQueryClient();
  const [selectedReceipt, setSelectedReceipt] = useState<Receipt | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [receiptToDelete, setReceiptToDelete] = useState<number | null>(null);

  const retryMutation = useMutation({
    mutationFn: api.retryReceipt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Ponawiam przetwarzanie...", {
        description: "AI spróbuje ponownie przeanalizować ten paragon.",
      });
    },
    onError: (err) => {
      console.error(err);
      toast.error("Błąd ponawiania.", {
        description:
          "Możliwe, że plik wygasł lub został usunięty. Wgraj go ponownie.",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteReceipt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] });
      toast.success("Paragon usunięty");
      setReceiptToDelete(null);
    },
    onError: () => toast.error("Nie udało się usunąć paragonu"),
  });

  const handleOpenModal = (receipt: Receipt) => {
    setSelectedReceipt(receipt);
    setIsModalOpen(true);
  };

  if (error) {
    return <div className="text-red-500">Error loading receipts.</div>;
  }

  return (
    <>
      <Card className="rounded-2xl border-0 shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Paragony</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-b border-muted">
                <TableHead className="text-muted-foreground">Sklep</TableHead>
                <TableHead className="text-muted-foreground">Data</TableHead>
                <TableHead className="text-muted-foreground">Status</TableHead>
                <TableHead className="text-right text-muted-foreground">
                  Kwota
                </TableHead>
                <TableHead className="w-[120px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="h-24 text-center text-muted-foreground"
                  >
                    Ładowanie danych...
                  </TableCell>
                </TableRow>
              ) : receipts.length === 0 ? (
                // Stan pusty (Empty State)
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="h-24 text-center text-muted-foreground"
                  >
                    Brak paragonów. Wgraj pierwszy! 🧾
                  </TableCell>
                </TableRow>
              ) : (
                receipts.map((receipt) => {
                  const isDone = receipt.status === "done";
                  const isError = receipt.status === "error";

                  let statusColor =
                    "bg-amber-50/50 text-amber-600 border-amber-100";
                  if (isDone)
                    statusColor =
                      "bg-emerald-50/50 text-emerald-600 border-emerald-100";
                  if (isError)
                    statusColor = "bg-red-50/50 text-red-600 border-red-100";

                  return (
                    <TableRow
                      key={receipt.id}
                      className="border-b border-muted/50"
                    >
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                            <Store className="h-4 w-4 text-muted-foreground" />
                          </div>
                          <span className="font-medium">
                            {receipt.merchant_name}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-gray-500">
                        {new Date(receipt.date).toLocaleDateString("pl-PL")}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={cn("rounded-md capitalize", statusColor)}
                        >
                          {receipt.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {receipt.total_amount.toFixed(2)} {receipt.currency}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {/* Przycisk Retry (tylko dla błędów) */}
                          {receipt.status === "error" && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                              onClick={() => retryMutation.mutate(receipt.id)}
                              disabled={retryMutation.isPending}
                              title="Błąd przetwarzania - Spróbuj ponownie"
                            >
                              <RefreshCcw
                                className={cn(
                                  "h-3.5 w-3.5",
                                  retryMutation.isPending && "animate-spin",
                                )}
                              />
                            </Button>
                          )}

                          {/* Przycisk Szczegóły/Edycja */}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-gray-500 hover:text-primary hover:bg-primary/10"
                            onClick={() => handleOpenModal(receipt)}
                            title="Szczegóły / Edycja"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>

                          {/* Przycisk Usuń */}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                            onClick={() => setReceiptToDelete(receipt.id)}
                            title="Usuń paragon"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Modal Szczegółów */}
      <ReceiptDetailModal
        receipt={selectedReceipt}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />

      {/* Modal Potwierdzenia Usunięcia */}
      <AlertDialog
        open={!!receiptToDelete}
        onOpenChange={(open) => !open && setReceiptToDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Czy na pewno chcesz usunąć ten paragon?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Tej operacji nie można cofnąć. Paragon zostanie trwale usunięty z
              bazy danych wraz ze wszystkimi pozycjami.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Anuluj</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                receiptToDelete && deleteMutation.mutate(receiptToDelete)
              }
              className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
            >
              Usuń
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
