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
import { Store, RefreshCcw, Eye, Trash2, ChevronLeft, ChevronRight } from "lucide-react";
import type { Receipt } from "@/types";
import { cn } from "@/lib/utils";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ReceiptDetailModal } from "./ReceiptDetailModal";

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
  
  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 5;

  const totalPages = Math.ceil(receipts.length / ITEMS_PER_PAGE) || 1;
  const paginatedReceipts = receipts.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

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
      if (paginatedReceipts.length === 1 && currentPage > 1) {
          setCurrentPage(prev => prev - 1);
      }
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
      <Card className="rounded-2xl border border-border/50 shadow-sm bg-card/50 backdrop-blur-sm overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-3">
            <CardTitle className="text-lg font-semibold">Paragony</CardTitle>
            <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-bold">
                {receipts.length}
            </Badge>
          </div>

          <div className="flex items-center gap-3">
              <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
                  Strona {currentPage} z {totalPages}
              </span>
              <div className="flex gap-1">
                  <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7 rounded-lg"
                      onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                      disabled={currentPage === 1}
                  >
                      <ChevronLeft className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7 rounded-lg"
                      onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                      disabled={currentPage === totalPages || totalPages === 1}
                  >
                      <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
              </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-b border-muted">
                <TableHead className="text-muted-foreground">Sklep</TableHead>
                <TableHead className="text-muted-foreground">Data</TableHead>
                <TableHead className="text-muted-foreground w-[140px]">Status</TableHead>
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
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="h-24 text-center text-muted-foreground"
                  >
                    Brak paragonów. Wgraj pierwszy! 🧾
                  </TableCell>
                </TableRow>
              ) : (
                paginatedReceipts.map((receipt) => {
                  return (
                    <TableRow
                      key={receipt.id}
                      className="border-b border-muted/50 cursor-pointer lg:cursor-default hover:bg-muted/30 lg:hover:bg-transparent transition-colors"
                      onClick={() => {
                        if (window.innerWidth < 1024) {
                          handleOpenModal(receipt);
                        }
                      }}
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
                        {receipt.date 
                          ? new Date(receipt.date).toLocaleDateString("pl-PL")
                          : "-"}
                      </TableCell>
                      <TableCell>
                        {(() => {
                          const isDone = receipt.status === "done";
                          const isError = receipt.status === "error";
                          
                          let colors = "bg-amber-100/50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-400/20";
                          if (isDone) colors = "bg-emerald-100/50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-400/20";
                          if (isError) colors = "bg-red-100/50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-400/20";

                          return (
                            <Badge
                              variant="outline"
                              className={cn("rounded-md capitalize w-24 justify-center font-semibold", colors)}
                            >
                              {receipt.status}
                            </Badge>
                          );
                        })()}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {receipt.total_amount.toFixed(2)} {receipt.currency}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {receipt.status === "error" && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                              onClick={(e) => {
                                e.stopPropagation();
                                retryMutation.mutate(receipt.id);
                              }}
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

                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-gray-500 hover:text-primary hover:bg-primary/10"
                            onClick={(e) => {
                                e.stopPropagation();
                                handleOpenModal(receipt);
                            }}
                            title="Szczegóły / Edycja"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>

                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                            onClick={(e) => {
                                e.stopPropagation();
                                setReceiptToDelete(receipt.id);
                            }}
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

      <ReceiptDetailModal
        receipt={selectedReceipt}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />

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