import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { AutoMergePolicy, BankCsvPreviewResponse } from "@/client";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Receipt, Upload, Loader2, FileText, Plus, Wallet, X } from "lucide-react";
import { TransactionsTable } from "@/components/dashboard/TransactionsTable";
import { toast } from "sonner";
import { useRef, useState } from "react";
import type { AxiosError } from "axios";
import { t } from "@/lib/i18n";
import { formatDate } from "@/lib/dates";
import { formatMoneyFixed } from "@/lib/money";
import { useIsMobile } from "@/hooks/use-mobile";
import { useTransactionActions } from "@/hooks/use-transaction-actions";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

export function TransactionsPage() {
  const { isDemo } = useAuth();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isMobile = useIsMobile();
  const { setQuickEntryOpen, renderModals } = useTransactionActions();
  const [searchParams, setSearchParams] = useSearchParams();
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [previewData, setPreviewData] = useState<BankCsvPreviewResponse | null>(null);
  const [importAccountId, setImportAccountId] = useState<string>("");
  const [mergePolicy, setMergePolicy] = useState<AutoMergePolicy>("auto");

  const accountIdParam = searchParams.get("accountId");
  const selectedAccountId = accountIdParam ? parseInt(accountIdParam) : null;

  const { data: transactions = [], isLoading, error } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.getTransactions(),
  });

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const activeAccounts = accounts.filter((a) => a.is_active !== false);
  const selectedAccount = accounts.find((a) => a.id === selectedAccountId);
  const filteredTransactions = selectedAccountId
    ? transactions.filter((t) => t.account_id === selectedAccountId || (t.type === "transfer" && t.transfer_id === selectedAccountId))
    : transactions;

  const resetImportModal = () => {
    setImportDialogOpen(false);
    setPendingImportFile(null);
    setPreviewData(null);
    setImportAccountId("");
    setMergePolicy("auto");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const previewMutation = useMutation({
    mutationFn: api.previewImportTransactions,
    onSuccess: (preview) => {
      setPreviewData(preview);
      const preferred =
        selectedAccountId ??
        preview.suggested_account_id ??
        activeAccounts[0]?.id ??
        null;
      setImportAccountId(preferred ? String(preferred) : "");
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      toast.error(t("transactions.import_error_title"), {
        description: err.response?.data?.detail || t("transactions.import_error_default"),
      });
      resetImportModal();
    },
  });

  const importMutation = useMutation({
    mutationFn: ({
      file,
      accountId,
      policy,
    }: {
      file: File;
      accountId: number;
      policy: AutoMergePolicy;
    }) =>
      api.importTransactions(file, {
        account_id: accountId,
        auto_merge_policy: policy,
        require_account: true,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
      let description: string;
      if (data.summary && typeof data.summary === "object" && data.summary.code === "CSV_IMPORT_COMPLETE") {
        description = t("errors.csv_import_complete", {
          imported: String(data.summary.imported),
          skipped: String(data.summary.skipped),
          filename: data.summary.filename,
        });
      } else {
        description = typeof data.summary === "string" ? data.summary : t("transactions.import_success");
      }
      toast.success(t("transactions.import_success"), {
        description,
      });
      resetImportModal();
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      toast.error(t("transactions.import_error_title"), {
        description: err.response?.data?.detail || t("transactions.import_error_default"),
      });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setPendingImportFile(file);
      setPreviewData(null);
      setImportDialogOpen(true);
      previewMutation.mutate(file);
    }
  };

  const handleConfirmImport = () => {
    if (!pendingImportFile) return;
    if (!importAccountId) {
      toast.error(t("transactions.import_modal.account_required_error"));
      return;
    }
    importMutation.mutate({
      file: pendingImportFile,
      accountId: parseInt(importAccountId, 10),
      policy: mergePolicy,
    });
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Receipt className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{t("transactions.page_title")}</h1>
        </div>

        <div className="flex items-center gap-2">
          {!isMobile && (
            <Button
              onClick={() => setQuickEntryOpen(true)}
              className="rounded-full font-bold shadow-lg shadow-primary/20 h-10 px-6 transition-all active:scale-95 mr-2"
            >
              <Plus className="mr-2 size-4" /> {t("dashboard.header.add_transaction")}
            </Button>
          )}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".csv,.pdf"
            className="hidden"
          />
          <Button 
            variant="outline" 
            className={cn(
              "gap-2 border-dashed",
              isDemo ? "opacity-50 cursor-not-allowed" : "border-primary/50 hover:border-primary"
            )}
            onClick={() => {
              if (isDemo) return;
              fileInputRef.current?.click();
            }}
            disabled={isDemo || importMutation.isPending}
            title={isDemo ? t("demo.disabled_in_demo") : undefined}
          >
            {importMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            {t("transactions.import_button")}
          </Button>
          
          <Button variant="ghost" size="icon" className="text-muted-foreground" title="Eksportuj dane">
            <FileText className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {selectedAccountId && selectedAccount && (
        <div className="flex items-center justify-between p-3 bg-primary/10 rounded-xl text-primary text-sm font-medium border border-primary/20">
          <div className="flex items-center gap-2">
            <Wallet className="size-4" />
            <span>
              {t("dashboard.recent_transactions.filter_active_prefix")}{" "}
              <strong>{selectedAccount.name}</strong>
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.delete("accountId");
              setSearchParams(next);
            }}
            className="h-7 px-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            <X className="size-3.5 mr-1" />
            {t("dashboard.recent_transactions.clear_filter")}
          </Button>
        </div>
      )}

      <div className="grid gap-6">
        <TransactionsTable
          transactions={filteredTransactions}
          categories={categories}
          isLoading={isLoading}
          error={error}
          selectedAccountId={selectedAccountId}
        />
      </div>

      {transactions.length > 0 && (
         <Card className="rounded-2xl border-border/50 bg-muted/20">
            <CardContent className="pt-6">
               <p className="text-xs text-muted-foreground text-center">
                  {t("transactions.tip")}
               </p>
            </CardContent>
         </Card>
      )}

      {/* Modals & Drawers */}
      {renderModals()}

      <Dialog
        open={importDialogOpen}
        onOpenChange={(open) => {
          if (!open && !importMutation.isPending) {
            resetImportModal();
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("transactions.import_modal.title")}</DialogTitle>
            <DialogDescription>{t("transactions.import_modal.subtitle")}</DialogDescription>
          </DialogHeader>

          {previewMutation.isPending ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin" />
              <span className="text-sm">{t("transactions.import_modal.preview_loading")}</span>
            </div>
          ) : (
            <div className="space-y-4">
              {previewData && (
                <div className="rounded-xl border bg-muted/40 p-3 space-y-2 text-xs">
                  <div className="font-medium truncate">
                    {t("transactions.import_modal.file_summary", { filename: previewData.filename })}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">
                      {t("transactions.import_modal.total_rows", { count: String(previewData.total_rows) })}
                    </Badge>
                    <Badge variant="outline" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20">
                      {t("transactions.import_modal.new_rows", { count: String(previewData.new_count) })}
                    </Badge>
                    {previewData.duplicate_count > 0 && (
                      <Badge variant="secondary">
                        {t("transactions.import_modal.duplicate_rows", {
                          count: String(previewData.duplicate_count),
                        })}
                      </Badge>
                    )}
                  </div>
                </div>
              )}

              <div className="space-y-1.5">
                <Label>{t("transactions.import_modal.account_label")}</Label>
                <Select value={importAccountId} onValueChange={setImportAccountId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("transactions.import_modal.account_placeholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {activeAccounts.map((acc) => (
                      <SelectItem key={acc.id} value={String(acc.id)}>
                        {acc.name}
                        {previewData?.suggested_account_id === acc.id
                          ? ` (${t("transactions.import_modal.account_suggested_badge")})`
                          : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>{t("transactions.import_modal.merge_policy_label")}</Label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setMergePolicy("auto")}
                    className={cn(
                      "rounded-xl border p-3 text-left transition-colors",
                      mergePolicy === "auto"
                        ? "border-primary bg-primary/5"
                        : "border-border hover:bg-muted/50"
                    )}
                  >
                    <div className="font-semibold text-xs">{t("transactions.import_modal.merge_auto_label")}</div>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      {t("transactions.import_modal.merge_auto_desc")}
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => setMergePolicy("manual")}
                    className={cn(
                      "rounded-xl border p-3 text-left transition-colors",
                      mergePolicy === "manual"
                        ? "border-primary bg-primary/5"
                        : "border-border hover:bg-muted/50"
                    )}
                  >
                    <div className="font-semibold text-xs">{t("transactions.import_modal.merge_manual_label")}</div>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      {t("transactions.import_modal.merge_manual_desc")}
                    </p>
                  </button>
                </div>
              </div>

              {previewData && previewData.rows && previewData.rows.length > 0 && (
                <div className="max-h-44 overflow-y-auto rounded-lg border divide-y text-xs">
                  {previewData.rows.slice(0, 8).map((row, idx) => (
                    <div
                      key={`${row.date}-${idx}`}
                      className={cn(
                        "flex items-center justify-between gap-2 px-3 py-2",
                        row.is_duplicate && "opacity-50"
                      )}
                    >
                      <div className="min-w-0">
                        <div className="font-medium truncate">{row.merchant_name}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {formatDate(row.date, "PPP")}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {row.is_duplicate && (
                          <Badge variant="outline" className="text-[10px]">
                            {t("transactions.import_modal.already_imported_badge")}
                          </Badge>
                        )}
                        <span className="font-semibold tabular-nums">
                          {formatMoneyFixed(row.amount)} {row.currency}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={resetImportModal}
              disabled={importMutation.isPending}
            >
              {t("transactions.import_modal.cancel_button")}
            </Button>
            <Button
              type="button"
              onClick={handleConfirmImport}
              disabled={
                previewMutation.isPending ||
                importMutation.isPending ||
                !importAccountId
              }
            >
              {importMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t("transactions.import_modal.importing_button")}
                </>
              ) : (
                t("transactions.import_modal.confirm_button", {
                  count: String(previewData?.new_count ?? 0),
                })
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
