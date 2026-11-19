import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Inbox,
  Loader2,
  Sparkles,
  AlertCircle,
  Plus,
  GitCompareArrows,
  Receipt,
  Trash2,
  RotateCcw,
  Check,
  Clock,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ImportJobRead, TransactionRead } from "@/client";
import { PendingVerificationList } from "@/components/inbox/PendingVerificationList";
import { ReconciliationPanel } from "@/components/inbox/ReconciliationPanel";
import { VerificationCard } from "@/components/inbox/VerificationCard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useIsMobile } from "@/hooks/use-mobile";
import { useTransactionActions } from "@/hooks/use-transaction-actions";
import { formatDate } from "@/lib/dates";
import { translateValidationMessage } from "@/lib/errorCodes";
import { formatMoneyFixed } from "@/lib/money";
import { getTransactionProvenance } from "@/lib/provenance";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

type InboxTab = "exceptions" | "reconciliation" | "rejected";
type SourceFilter = "all" | "ocr_photo" | "merchant_api" | "e_receipt" | "bank_csv";

function getRejectedSourceLabel(tx: TransactionRead): string | null {
  return getTransactionProvenance(tx).sourceLabel;
}

function getJobStatusMeta(job: ImportJobRead): {
  label: string;
  variant: "secondary" | "outline" | "destructive";
} {
  if (job.status === "failed") {
    return { label: t("inbox.jobs.status_failed"), variant: "destructive" };
  }
  if (job.status === "running") {
    return { label: t("inbox.jobs.status_running"), variant: "secondary" };
  }
  if (job.status === "completed") {
    return { label: t("inbox.jobs.status_completed"), variant: "outline" };
  }
  if (job.status === "pending" && job.attempt_count > 0) {
    return { label: t("inbox.jobs.status_retryable"), variant: "outline" };
  }
  return { label: t("inbox.jobs.status_pending"), variant: "secondary" };
}

export function InboxPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<InboxTab>("exceptions");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checkedIds, setCheckedIds] = useState<number[]>([]);
  const [bulkAccountOverride, setBulkAccountOverride] = useState<string>("");
  const [jobsExpandedOverride, setJobsExpandedOverride] = useState<boolean | null>(null);
  const isMobile = useIsMobile();
  const { setQuickEntryOpen, renderModals } = useTransactionActions();

  const { data: importJobs = [] } = useQuery({
    queryKey: ["import-jobs"],
    queryFn: () =>
      typeof api.getImportJobs === "function"
        ? api.getImportJobs({ job_type: "document_ingest", limit: 25 })
        : Promise.resolve([]),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      const hasActive = jobs.some((j) => j.status === "pending" || j.status === "running");
      return hasActive ? 2000 : 8000;
    },
  });

  const activeJobsCount = importJobs.filter(
    (j) => j.status === "pending" || j.status === "running"
  ).length;
  const failedJobsCount = importJobs.filter((j) => j.status === "failed").length;
  const hasActiveJobs = activeJobsCount > 0;
  const isJobsPanelExpanded = jobsExpandedOverride ?? (activeJobsCount > 0 || failedJobsCount > 0);

  const {
    data: transactions = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["inbox", "exceptions", sourceFilter],
    queryFn: () =>
      api.getInbox(
        sourceFilter === "all"
          ? { tab: "exceptions" }
          : { tab: "exceptions", source_type: sourceFilter }
      ),
    refetchInterval: hasActiveJobs ? 2000 : 5000,
  });

  const {
    data: rejectedTransactions = [],
    isLoading: isRejectedLoading,
  } = useQuery({
    queryKey: ["inbox", "rejected"],
    queryFn: () => api.getInbox({ tab: "rejected" }),
  });

  const { data: reconciliationSummary } = useQuery({
    queryKey: ["reconciliation", "pending"],
    queryFn: () => api.getReconciliationCandidates("pending"),
  });

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: api.getAccounts,
  });

  const pendingReconciliationCount = reconciliationSummary?.pending_count ?? 0;
  const rejectedCount = rejectedTransactions.length;

  const activeAccounts = accounts.filter((acc) => acc.is_active !== false);
  const suggestedAccountId =
    transactions.find((item) => item.suggested_account_id != null)?.suggested_account_id ??
    activeAccounts[0]?.id ??
    null;
  const effectiveBulkAccountId = bulkAccountOverride || (suggestedAccountId ? String(suggestedAccountId) : "");

  const currentTransaction =
    transactions.find((tx) => tx.id === selectedId) ||
    (transactions.length > 0 && !isMobile ? transactions[0] : null);

  const visibleIdSet = new Set(transactions.map((tx) => tx.id));
  const activeCheckedIds = checkedIds.filter((id) => visibleIdSet.has(id));
  const allChecked = transactions.length > 0 && activeCheckedIds.length === transactions.length;

  const invalidateInboxAndLedger = () => {
    queryClient.invalidateQueries({ queryKey: ["inbox"] });
    queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    queryClient.invalidateQueries({ queryKey: ["status"] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
  };

  const handleSuccess = () => {
    invalidateInboxAndLedger();
    if (isMobile) {
      setSelectedId(null);
    }
  };

  const bulkApproveMutation = useMutation({
    mutationFn: ({ ids, accountId }: { ids: number[]; accountId: number }) =>
      api.bulkApproveInbox({ transaction_ids: ids, account_id: accountId }),
    onSuccess: (res) => {
      invalidateInboxAndLedger();
      setCheckedIds([]);
      if ((res.skipped_ids?.length ?? 0) > 0) {
        toast.info(
          t("inbox.bulk.approve_partial", {
            approved: String(res.approved_count),
            skipped: String(res.skipped_ids?.length ?? 0),
          })
        );
      } else {
        toast.success(t("inbox.bulk.approve_success", { count: String(res.approved_count) }));
      }
    },
    onError: () => {
      toast.error(t("inbox.bulk.approve_error"));
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (txId: number) => api.restoreInboxItem(txId),
    onSuccess: () => {
      invalidateInboxAndLedger();
      toast.success(t("inbox.rejected.restore_success"));
    },
    onError: () => {
      toast.error(t("inbox.rejected.restore_error"));
    },
  });

  const purgeMutation = useMutation({
    mutationFn: (txId: number) => api.deleteTransaction(txId, { preserveSource: false }),
    onSuccess: () => {
      invalidateInboxAndLedger();
      toast.success(t("inbox.rejected.purge_success"));
    },
    onError: () => {
      toast.error(t("inbox.rejected.purge_error"));
    },
  });

  const retryJobMutation = useMutation({
    mutationFn: (jobId: number) => api.retryImportJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      toast.success(t("inbox.jobs.retry_success"));
    },
    onError: () => {
      toast.error(t("inbox.jobs.retry_error"));
    },
  });

  const handleToggleSelect = (txId: number) => {
    setCheckedIds((prev) =>
      prev.includes(txId) ? prev.filter((id) => id !== txId) : [...prev, txId]
    );
  };

  const handleToggleAll = () => {
    if (allChecked) {
      setCheckedIds([]);
    } else {
      setCheckedIds(transactions.map((tx) => tx.id));
    }
  };

  const handleBulkApprove = () => {
    if (!effectiveBulkAccountId) {
      toast.error(t("inbox.bulk.account_required"));
      return;
    }
    if (activeCheckedIds.length === 0) return;
    bulkApproveMutation.mutate({
      ids: activeCheckedIds,
      accountId: parseInt(effectiveBulkAccountId, 10),
    });
  };

  const sourceFilters: Array<{ value: SourceFilter; label: string }> = [
    { value: "all", label: t("inbox.source_filters.all") },
    { value: "ocr_photo", label: t("inbox.source_filters.ocr_photo") },
    { value: "merchant_api", label: t("inbox.source_filters.merchant_api") },
    { value: "e_receipt", label: t("inbox.source_filters.e_receipt") },
    { value: "bank_csv", label: t("inbox.source_filters.bank_csv") },
  ];

  const showList = !isMobile || (isMobile && !selectedId);
  const showDetail = currentTransaction && (!isMobile || (isMobile && selectedId));

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] overflow-hidden">
      {(!isMobile || !selectedId) && (
        <div className="flex items-center justify-between px-4 md:px-8 py-4 md:py-6 bg-background/50 backdrop-blur-md border-b shrink-0">
          <div className="flex items-center gap-3 md:gap-4">
            <div className="p-2 md:p-2.5 bg-primary/10 rounded-xl shadow-inner">
              <Inbox className="h-5 w-5 md:h-6 md:w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-xl md:text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">
                {t("inbox.title")}
              </h1>
              {!isMobile && (
                <p className="text-sm text-muted-foreground flex items-center gap-1.5 mt-0.5">
                  <Sparkles className="h-3 w-3 text-amber-500" />
                  {t("inbox.verify_subtitle")}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-4">
            {!isMobile && (
              <Button
                onClick={() => setQuickEntryOpen(true)}
                className="rounded-full font-bold shadow-lg shadow-primary/20 h-10 px-6 transition-all active:scale-95"
              >
                <Plus className="mr-2 size-4" /> {t("dashboard.header.add_transaction")}
              </Button>
            )}

            {transactions.length > 0 && (
              <div className="flex items-center gap-2 px-2 md:px-3 py-1 md:py-1.5 bg-primary/5 rounded-full border border-primary/10">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                </span>
                <span className="text-[10px] md:text-xs font-bold text-primary">
                  {transactions.length} {t("inbox.pending_count_label")}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {(!isMobile || !selectedId) && (
        <div className="flex flex-wrap items-center gap-2 px-4 md:px-8 py-2.5 border-b bg-background/40 shrink-0">
          <Button
            variant={activeTab === "exceptions" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("exceptions")}
            className="gap-2"
          >
            <Receipt className="h-4 w-4" />
            <span>{t("inbox.tabs.exceptions")}</span>
            {transactions.length > 0 && (
              <Badge variant={activeTab === "exceptions" ? "secondary" : "outline"} className="text-[10px] h-4 px-1.5">
                {transactions.length}
              </Badge>
            )}
          </Button>
          <Button
            variant={activeTab === "reconciliation" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("reconciliation")}
            className="gap-2"
          >
            <GitCompareArrows className="h-4 w-4" />
            <span>{t("inbox.tabs.reconciliation")}</span>
            {pendingReconciliationCount > 0 && (
              <Badge
                variant={activeTab === "reconciliation" ? "secondary" : "outline"}
                className="text-[10px] h-4 px-1.5"
              >
                {pendingReconciliationCount}
              </Badge>
            )}
          </Button>
          <Button
            variant={activeTab === "rejected" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("rejected")}
            className="gap-2"
          >
            <Trash2 className="h-4 w-4" />
            <span>{t("inbox.tabs.rejected")}</span>
            {rejectedCount > 0 && (
              <Badge
                variant={activeTab === "rejected" ? "secondary" : "outline"}
                className="text-[10px] h-4 px-1.5"
              >
                {rejectedCount}
              </Badge>
            )}
          </Button>
        </div>
      )}

      {activeTab === "reconciliation" ? (
        <div className={cn("flex-1 flex overflow-hidden bg-muted/20", isMobile ? "p-4" : "p-8")}>
          <ReconciliationPanel />
        </div>
      ) : activeTab === "rejected" ? (
        <div className={cn("flex-1 overflow-y-auto bg-muted/20", isMobile ? "p-4" : "p-8")}>
          {isRejectedLoading ? (
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
            </div>
          ) : rejectedTransactions.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed rounded-2xl bg-card/40 max-w-2xl mx-auto">
              <Trash2 className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-lg font-medium text-muted-foreground">{t("inbox.rejected.empty_title")}</h3>
              <p className="text-sm text-muted-foreground/70 max-w-md mt-1">
                {t("inbox.rejected.empty_description")}
              </p>
            </div>
          ) : (
            <div className="space-y-3 max-w-4xl">
              {rejectedTransactions.map((tx) => {
                const srcLabel = getRejectedSourceLabel(tx);
                return (
                  <Card key={tx.id} className="border-border/60 bg-card/80">
                    <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div className="space-y-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold text-sm truncate">
                            {tx.merchant_name || t("inbox.list.processing_placeholder")}
                          </span>
                          {srcLabel && (
                            <Badge variant="secondary" className="text-[10px] h-5">
                              {srcLabel}
                            </Badge>
                          )}
                          <span className="font-bold text-sm tabular-nums">
                            {formatMoneyFixed(tx.total_amount ?? "0.00")} {tx.currency}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span>{tx.date ? formatDate(tx.date, "PPP") : t("inbox.list.no_date")}</span>
                          {tx.rejection_reason && (
                            <span>
                              • {t("inbox.rejected.reason_prefix")}: {tx.rejection_reason}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={restoreMutation.isPending}
                          onClick={() => restoreMutation.mutate(tx.id)}
                          className="gap-1.5"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          {t("inbox.rejected.restore_button")}
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={purgeMutation.isPending}
                              className="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              {t("inbox.rejected.purge_button")}
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>{t("inbox.rejected.purge_dialog_title")}</AlertDialogTitle>
                              <AlertDialogDescription>
                                {t("inbox.rejected.purge_dialog_description")}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>{t("inbox.rejected.purge_dialog_cancel")}</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => purgeMutation.mutate(tx.id)}
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              >
                                {t("inbox.rejected.purge_dialog_confirm")}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div
          className={cn(
            "flex-1 flex overflow-hidden bg-muted/20",
            isMobile ? "p-0" : "p-8 gap-8"
          )}
        >
          {showList && (
            <div
              className={cn(
                "flex flex-col gap-3 overflow-hidden shrink-0",
                isMobile ? "w-full p-4" : "w-96"
              )}
            >
              {importJobs.length > 0 && (
                <div className="rounded-xl border border-border/60 bg-card/80 p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Clock className="h-3.5 w-3.5 text-primary shrink-0" />
                      <span className="text-xs font-semibold truncate">
                        {t("inbox.jobs.panel_title")}
                      </span>
                      {activeJobsCount > 0 && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                          {t("inbox.jobs.active_count", { count: String(activeJobsCount) })}
                        </Badge>
                      )}
                      {failedJobsCount > 0 && (
                        <Badge variant="destructive" className="text-[10px] h-4 px-1.5">
                          {t("inbox.jobs.failed_count", { count: String(failedJobsCount) })}
                        </Badge>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[11px] gap-1 shrink-0"
                      onClick={() => setJobsExpandedOverride(!isJobsPanelExpanded)}
                    >
                      <span>
                        {isJobsPanelExpanded ? t("inbox.jobs.toggle_hide") : t("inbox.jobs.toggle_show")}
                      </span>
                      {isJobsPanelExpanded ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </Button>
                  </div>

                  {isJobsPanelExpanded && (
                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-0.5">
                      {importJobs.map((job) => {
                        const statusMeta = getJobStatusMeta(job);
                        const canRetry =
                          job.status === "failed" ||
                          (job.status === "pending" && job.attempt_count > 0);
                        return (
                          <div
                            key={job.id}
                            onClick={() => {
                              if (job.transaction_id) {
                                setSelectedId(job.transaction_id);
                              }
                            }}
                            className={cn(
                              "flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs bg-muted/20",
                              job.transaction_id && "cursor-pointer hover:border-primary/40"
                            )}
                          >
                            <div className="min-w-0 space-y-0.5">
                              <p className="font-medium truncate">
                                {job.source_filename ||
                                  t("inbox.jobs.unnamed_file", { id: String(job.id) })}
                              </p>
                              <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                <span>
                                  {t("inbox.jobs.attempt_label", {
                                    attempt: String(job.attempt_count),
                                    max: String(job.max_attempts),
                                  })}
                                </span>
                                {job.last_error_code && (
                                  <span className="truncate">
                                    • {translateValidationMessage(job.last_error_code)}
                                  </span>
                                )}
                              </div>
                            </div>

                            <div className="flex items-center gap-1.5 shrink-0">
                              <Badge variant={statusMeta.variant} className="text-[10px] h-5">
                                {statusMeta.label}
                              </Badge>
                              {canRetry && (
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={retryJobMutation.isPending}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    retryJobMutation.mutate(job.id);
                                  }}
                                  className="h-6 px-2 text-[10px] gap-1"
                                >
                                  <RotateCcw className="h-3 w-3" />
                                  {t("inbox.jobs.retry_button")}
                                </Button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-1.5">
                {sourceFilters.map((f) => (
                  <Button
                    key={f.value}
                    variant={sourceFilter === f.value ? "secondary" : "ghost"}
                    size="sm"
                    className="h-7 px-2.5 text-xs"
                    onClick={() => setSourceFilter(f.value)}
                  >
                    {f.label}
                  </Button>
                ))}
              </div>

              {transactions.length > 0 && (
                <div className="rounded-xl border border-border/60 bg-card/80 p-3 space-y-2.5">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <label className="inline-flex items-center gap-2 cursor-pointer font-medium">
                      <input
                        type="checkbox"
                        checked={allChecked}
                        onChange={handleToggleAll}
                        className="h-4 w-4 rounded border-border accent-primary cursor-pointer"
                      />
                      <span>{t("inbox.bulk.select_all")}</span>
                    </label>
                    {activeCheckedIds.length > 0 && (
                      <span className="font-semibold text-primary">
                        {t("inbox.bulk.selected_count", { count: String(activeCheckedIds.length) })}
                      </span>
                    )}
                  </div>

                  {activeCheckedIds.length > 0 && (
                    <div className="flex flex-col sm:flex-row gap-2 pt-1">
                      <Select
                        value={effectiveBulkAccountId}
                        onValueChange={setBulkAccountOverride}
                      >
                        <SelectTrigger className="h-8 text-xs flex-1">
                          <SelectValue placeholder={t("inbox.bulk.account_placeholder")} />
                        </SelectTrigger>
                        <SelectContent>
                          {activeAccounts.map((acc) => (
                            <SelectItem key={acc.id} value={String(acc.id)}>
                              {acc.name}
                              {suggestedAccountId === acc.id
                                ? ` (${t("inbox.bulk.suggested_suffix")})`
                                : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        className="h-8 text-xs shrink-0 gap-1"
                        disabled={bulkApproveMutation.isPending || !effectiveBulkAccountId}
                        onClick={handleBulkApprove}
                      >
                        {bulkApproveMutation.isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                        {bulkApproveMutation.isPending
                          ? t("inbox.bulk.approving_button")
                          : t("inbox.bulk.approve_button")}
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {!isMobile && (
                <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground/60 px-1">
                  {t("inbox.pending_section_header")}
                </h3>
              )}
              <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar">
                {isLoading ? (
                  <div className="flex items-center justify-center p-12">
                    <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
                  </div>
                ) : error ? (
                  <Card className="border-destructive/20 bg-destructive/5">
                    <CardContent className="p-4 flex items-center gap-2 text-destructive">
                      <AlertCircle className="h-4 w-4" />
                      <span className="text-xs font-medium">{t("inbox.load_error")}</span>
                    </CardContent>
                  </Card>
                ) : (
                  <PendingVerificationList
                    transactions={transactions}
                    selectedId={currentTransaction?.id}
                    selectedIds={activeCheckedIds}
                    onToggleSelect={handleToggleSelect}
                    onSelect={(tx) => setSelectedId(tx.id)}
                  />
                )}
              </div>
            </div>
          )}

          {showDetail && (
            <div className={cn("flex-1 flex flex-col overflow-hidden", isMobile ? "p-0" : "")}>
              <VerificationCard
                key={currentTransaction.id}
                transaction={currentTransaction}
                onSuccess={handleSuccess}
                onBack={isMobile ? () => setSelectedId(null) : undefined}
              />
            </div>
          )}
        </div>
      )}
      {renderModals()}
    </div>
  );
}
