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
import type { Transaction } from "@/types";
import { cn } from "@/lib/utils";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { TransactionDetailModal } from "./TransactionDetailModal";

interface TransactionsTableProps {
  transactions: Transaction[];
  isLoading?: boolean;
  error?: unknown;
}

export function TransactionsTable({
  transactions,
  isLoading,
  error,
}: TransactionsTableProps) {
  const queryClient = useQueryClient();
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [transactionToDelete, setTransactionToDelete] = useState<number | null>(null);
  
  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 5;

  const totalPages = Math.ceil(transactions.length / ITEMS_PER_PAGE) || 1;
  const paginatedTransactions = transactions.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  const retryMutation = useMutation({
    mutationFn: api.retryTransaction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Ponawiam przetwarzanie...", {
        description: "AI spróbuje ponownie przeanalizować ten transakcję.",
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
    mutationFn: api.deleteTransaction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Transakcja usunięty");
      setTransactionToDelete(null);
      if (paginatedTransactions.length === 1 && currentPage > 1) {
          setCurrentPage(prev => prev - 1);
      }
    },
    onError: () => toast.error("Nie udało się usunąć transakcjęu"),
  });

  const handleOpenModal = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
    setIsModalOpen(true);
  };

  if (error) {
    return <div className="text-red-500">Error loading transactions.</div>;
  }

  return (
    <>
      <Card className="rounded-2xl border border-border/50 shadow-sm bg-card/50 backdrop-blur-sm overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-3">
            <CardTitle className="text-lg font-semibold">Transakcje</CardTitle>
            <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-bold">
                {transactions.length}
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
                <TableHead className="text-muted-foreground">Odbiorca/Sklep</TableHead>
                <TableHead className="text-muted-foreground">Typ</TableHead>
                <TableHead className="text-muted-foreground">Data</TableHead>
                <TableHead className="text-muted-foreground w-[140px]">Status AI</TableHead>
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
                    colSpan={6}
                    className="h-24 text-center text-muted-foreground"
                  >
                    Ładowanie danych...
                  </TableCell>
                </TableRow>
              ) : transactions.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="h-24 text-center text-muted-foreground"
                  >
                    Brak transakcji. Dodaj pierwszą! 🧾
                  </TableCell>
                </TableRow>
              ) : (
                paginatedTransactions.map((transaction) => {
                  return (
                    <TableRow
                      key={transaction.id}
                      className="border-b border-muted/50 cursor-pointer lg:cursor-default hover:bg-muted/30 lg:hover:bg-transparent transition-colors"
                      onClick={() => {
                        if (window.innerWidth < 1024) {
                          handleOpenModal(transaction);
                        }
                      }}
                    >
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                            <Store className="h-4 w-4 text-muted-foreground" />
                          </div>
                          <div className="flex flex-col">
                            <span className="font-medium">
                              {transaction.merchant_name}
                            </span>
                            <div className="flex flex-wrap gap-1 mt-0.5">
                              {transaction.tags?.map(tag => (
                                <span 
                                  key={tag.id} 
                                  className="text-[9px] text-white px-1.5 py-0 rounded-sm font-bold shadow-xs"
                                  style={{ backgroundColor: tag.color || "#9ca3af" }}
                                >
                                  #{tag.name}
                                </span>
                              ))}
                            </div>
                          </div>
                          </div>
                          </TableCell>
                          <TableCell>
                          {transaction.type === 'expense' && (
                          <Badge variant="outline" className="text-red-500 bg-red-500/5 border-red-500/20 text-[10px] uppercase font-bold">Wydatek</Badge>
                          )}
                          {transaction.type === 'income' && (
                          <Badge variant="outline" className="text-green-500 bg-green-500/5 border-green-500/20 text-[10px] uppercase font-bold">Przychód</Badge>
                          )}
                          {transaction.type === 'transfer' && (
                          <Badge variant="outline" className="text-blue-500 bg-blue-500/5 border-blue-500/20 text-[10px] uppercase font-bold">Transfer</Badge>
                          )}
                          </TableCell>
                          <TableCell className="text-gray-500 text-sm">
                        {transaction.date 
                          ? new Date(transaction.date).toLocaleDateString("pl-PL")
                          : "-"}
                      </TableCell>
                      <TableCell>
                        {(() => {
                          const scanStatus = transaction.receipt_scan?.status;
                          if (!scanStatus) return null;

                          const isDone = scanStatus === "done";
                          const isError = scanStatus === "error";

                          let colors = "bg-amber-100/50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-400/20";
                          if (isDone) colors = "bg-emerald-100/50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-400/20";
                          if (isError) colors = "bg-red-100/50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-400/20";

                          return (
                            <Badge
                              variant="outline"
                              className={cn("rounded-md capitalize w-24 justify-center font-semibold", colors)}
                            >
                              {scanStatus}
                            </Badge>
                          );
                        })()}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {transaction.total_amount.toFixed(2)} {transaction.currency}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {transaction.receipt_scan?.status === "error" && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                              onClick={(e) => {
                                e.stopPropagation();
                                retryMutation.mutate(transaction.id);
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
                                handleOpenModal(transaction);
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
                                setTransactionToDelete(transaction.id);
                            }}
                            title="Usuń transakcję"
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

      <TransactionDetailModal
        transaction={selectedTransaction}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />

      <AlertDialog
        open={!!transactionToDelete}
        onOpenChange={(open) => !open && setTransactionToDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Czy na pewno chcesz usunąć ten transakcję?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Tej operacji nie można cofnąć. Transakcja zostanie trwale usunięty z
              bazy danych wraz ze wszystkimi pozycjami.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Anuluj</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                transactionToDelete && deleteMutation.mutate(transactionToDelete)
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