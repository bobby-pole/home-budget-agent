import { t } from "@/lib/i18n";
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
import { Store, RefreshCcw, Eye, Trash2, ChevronLeft, ChevronRight, ArrowUpRight, ArrowDownRight } from "lucide-react";
import type { TransactionRead as Transaction, CategoryRead } from "@/client";
import { cn } from "@/lib/utils";
import { getIntlLocale } from "@/lib/dates";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { TransactionDetailModal } from "./TransactionDetailModal";
import { CATEGORY_LABELS } from "@/lib/constants";

interface TransactionsTableProps {
  transactions: Transaction[];
  categories?: CategoryRead[];
  isLoading?: boolean;
  error?: unknown;
}

export function TransactionsTable({
  transactions,
  categories = [],
  isLoading,
  error,
}: TransactionsTableProps) {
  const queryClient = useQueryClient();
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [transactionToDelete, setTransactionToDelete] = useState<number | null>(null);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 15;

  const totalPages = Math.ceil(transactions.length / ITEMS_PER_PAGE) || 1;
  const paginatedTransactions = transactions.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  const retryMutation = useMutation({
    mutationFn: api.retryTransaction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success(t("transactions.table.retry_toast"), {
        description: t("transactions.table.retry_toast_description"),
      });
    },
    onError: (err) => {
      console.error(err);
      toast.error(t("transactions.table.retry_error_title"), {
        description: t("transactions.table.retry_error_description"),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteTransaction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success(t("transactions.table.deleted_toast"));
      setTransactionToDelete(null);
      if (paginatedTransactions.length === 1 && currentPage > 1) {
        setCurrentPage(prev => prev - 1);
      }
    },
    onError: () => toast.error(t("transactions.table.delete_error_toast")),
  });

  const handleOpenModal = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
    setIsModalOpen(true);
  };

  if (error) {
    return <div className="text-red-500">{t("transactions.error_loading")}</div>;
  }

  return (
    <>
      <Card className="rounded-2xl border border-border/50 shadow-sm bg-card/50 backdrop-blur-sm overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-3">
            <CardTitle className="text-lg font-semibold">{t("transactions.table.title")}</CardTitle>
            <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-bold">
              {transactions.length}
            </Badge>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
              {t("transactions.table.page_info").replace("{current}", String(currentPage)).replace("{total}", String(totalPages))}
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
          {/* Mobile / tablet — card list (visible below lg) */}
          <div className="lg:hidden">
            {isLoading ? (
              <div className="py-12 text-center text-muted-foreground text-sm">
                {t("transactions.table.loading")}
              </div>
            ) : transactions.length === 0 ? (
              <div className="py-12 text-center text-muted-foreground text-sm">
                {t("transactions.table.empty")}
              </div>
            ) : (
              <div className="divide-y divide-border/50">
                {paginatedTransactions.map((transaction) => {
                  const isIncome = transaction.type === "income";
                  const isExpense = transaction.type === "expense";
                  const isTransfer = transaction.type === "transfer";
                  const category = categories.find((c) => c.id === transaction.category_id);
                  const categoryIcon = category?.icon;
                  const categoryName = category
                    ? (CATEGORY_LABELS[category.name] || category.name)
                    : null;
                  const dateLabel = transaction.date
                    ? new Date(transaction.date).toLocaleDateString(getIntlLocale(), { day: "numeric", month: "short" })
                    : "-";
                  const scanStatus = transaction.receipt_scan?.status;
                  const typeLabel = isIncome
                    ? t("transactions.table.type_income")
                    : isTransfer
                      ? t("transactions.table.type_transfer")
                      : t("transactions.table.type_expense");

                  return (
                    <div
                      key={transaction.id}
                      className="flex items-center gap-3 py-2.5 cursor-pointer hover:bg-muted/30 transition-colors -mx-6 px-6"
                      onClick={() => handleOpenModal(transaction)}
                    >
                      {/* Icon — matches RecentTransactionsList */}
                      <div className={cn(
                        "size-11 rounded-full flex items-center justify-center shrink-0 shadow-inner text-xl",
                        isIncome ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                        isExpense && categoryIcon ? "bg-muted" :
                        isExpense ? "bg-orange-100 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400" :
                        "bg-muted text-muted-foreground"
                      )}>
                        {categoryIcon ? categoryIcon : (isIncome ? <ArrowUpRight className="size-5" /> :
                         isExpense ? <Store className="size-5" /> :
                         <ArrowDownRight className="size-5" />)}
                      </div>

                      {/* Details (name + metadata wrap) */}
                      <div className="flex flex-col min-w-0 flex-1">
                        <span className="text-sm font-semibold truncate leading-tight">
                          {transaction.merchant_name}
                        </span>
                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 mt-0.5 text-[11px] text-muted-foreground font-medium">
                          <span className={cn(
                            "uppercase font-bold tracking-wide",
                            isIncome ? "text-emerald-600 dark:text-emerald-400" :
                            isTransfer ? "text-blue-600 dark:text-blue-400" :
                            "text-red-500"
                          )}>
                            {typeLabel}
                          </span>
                          {categoryName && (
                            <>
                              <span aria-hidden>•</span>
                              <span>{categoryName}</span>
                            </>
                          )}
                          <span aria-hidden>•</span>
                          <span>{dateLabel}</span>
                          {scanStatus && (
                            <>
                              <span aria-hidden>•</span>
                              <Badge
                                variant="outline"
                                className={cn(
                                  "h-4 px-1.5 text-[9px] uppercase font-bold rounded-md leading-none",
                                  scanStatus === "done" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-400/30",
                                  scanStatus === "error" && "bg-red-500/10 text-red-700 dark:text-red-400 border-red-400/30",
                                  scanStatus !== "done" && scanStatus !== "error" && "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-400/30",
                                )}
                              >
                                {scanStatus}
                              </Badge>
                            </>
                          )}
                          {transaction.tags?.map((tag) => (
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

                      {/* Amount + inline actions, vertically grouped on the right */}
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className={cn(
                          "text-sm font-bold tabular-nums whitespace-nowrap",
                          isIncome ? "text-emerald-600 dark:text-emerald-400" :
                          isTransfer ? "text-blue-600 dark:text-blue-400" : "text-destructive"
                        )}>
                          {isIncome ? "+" : isTransfer ? "" : "-"}
                          {(transaction.total_amount ?? 0).toFixed(2)} {transaction.currency ?? "PLN"}
                        </span>
                        <div className="flex items-center gap-0.5 -mr-1.5">
                          {scanStatus === "error" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 text-red-600 hover:bg-red-500/10"
                              onClick={(e) => {
                                e.stopPropagation();
                                retryMutation.mutate(transaction.id);
                              }}
                              disabled={retryMutation.isPending}
                              title={t("transactions.table.retry_title")}
                            >
                              <RefreshCcw className={cn("h-3.5 w-3.5", retryMutation.isPending && "animate-spin")} />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-muted-foreground hover:text-primary hover:bg-primary/10"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleOpenModal(transaction);
                            }}
                            title={t("transactions.table.details_title")}
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-muted-foreground/70 hover:text-red-600 hover:bg-red-500/10"
                            onClick={(e) => {
                              e.stopPropagation();
                              setTransactionToDelete(transaction.id);
                            }}
                            title={t("transactions.table.delete_title")}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Desktop — table (visible from lg up) */}
          <Table className="hidden lg:table">
            <TableHeader>
              <TableRow className="border-b border-muted">
                <TableHead className="text-muted-foreground">{t("transactions.table.col_merchant")}</TableHead>
                <TableHead className="text-muted-foreground">{t("transactions.table.col_type")}</TableHead>
                <TableHead className="text-muted-foreground">{t("transactions.table.col_date")}</TableHead>
                <TableHead className="text-muted-foreground w-[140px]">{t("transactions.table.col_status")}</TableHead>
                <TableHead className="text-right text-muted-foreground">
                  {t("transactions.table.col_amount")}
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
                    {t("transactions.table.loading")}
                  </TableCell>
                </TableRow>
              ) : transactions.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="h-24 text-center text-muted-foreground"
                  >
                    {t("transactions.table.empty")}
                  </TableCell>
                </TableRow>
              ) : (
                paginatedTransactions.map((transaction) => {
                  const isIncome = transaction.type === "income";
                  const isExpense = transaction.type === "expense";
                  const category = categories.find((c) => c.id === transaction.category_id);
                  const categoryIcon = category?.icon;

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
                          <div className={cn(
                            "flex h-9 w-9 items-center justify-center rounded-full shadow-inner shrink-0 text-base",
                            isIncome ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                            isExpense && categoryIcon ? "bg-muted" :
                            isExpense ? "bg-orange-100 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400" :
                            "bg-muted text-muted-foreground"
                          )}>
                            {categoryIcon ? categoryIcon : (isIncome ? <ArrowUpRight className="h-4 w-4" /> :
                             isExpense ? <Store className="h-4 w-4" /> :
                             <ArrowDownRight className="h-4 w-4" />)}
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
                          <Badge variant="outline" className="text-red-500 bg-red-500/5 border-red-500/20 text-[10px] uppercase font-bold">{t("transactions.table.type_expense")}</Badge>
                        )}
                        {transaction.type === 'income' && (
                          <Badge variant="outline" className="text-green-500 bg-green-500/5 border-green-500/20 text-[10px] uppercase font-bold">{t("transactions.table.type_income")}</Badge>
                        )}
                        {transaction.type === 'transfer' && (
                          <Badge variant="outline" className="text-blue-500 bg-blue-500/5 border-blue-500/20 text-[10px] uppercase font-bold">{t("transactions.table.type_transfer")}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-gray-500 text-sm">
                        {transaction.date
                          ? new Date(transaction.date).toLocaleDateString(getIntlLocale())
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
                      <TableCell className={cn(
                        "text-right font-semibold whitespace-nowrap",
                        transaction.type === 'income' ? "text-emerald-600 dark:text-emerald-400" :
                          transaction.type === 'transfer' ? "text-blue-600 dark:text-blue-400" : ""
                      )}>
                        {transaction.type === 'income' ? "+" : transaction.type === 'transfer' ? "" : "-"}
                        {(transaction.total_amount ?? 0).toFixed(2)} {transaction.currency ?? "PLN"}
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
                              title={t("transactions.table.retry_title")}
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
                            title={t("transactions.table.details_title")}
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
                            title={t("transactions.table.delete_title")}
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
              {t("transactions.table.delete_dialog_title")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("transactions.table.delete_dialog_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("transactions.table.delete_dialog_cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                transactionToDelete && deleteMutation.mutate(transactionToDelete)
              }
              className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
            >
              {t("transactions.table.delete_dialog_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}