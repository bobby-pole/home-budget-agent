import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  GitCompareArrows,
  Landmark,
  Link2Off,
  Loader2,
  Receipt,
  RefreshCw,
  X,
} from "lucide-react";
import { toast } from "sonner";

import type {
  ReconciliationLinkRead,
  ReconciliationMatchKind,
  ReconciliationSignalRead,
  ReconciliationStatus,
  ReconciliationTransactionSummary,
} from "@/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/dates";
import { t } from "@/lib/i18n";
import { formatMoneyFixed } from "@/lib/money";
import { cn } from "@/lib/utils";

type FilterValue = ReconciliationStatus | "all";

function extractErrorMessage(err: unknown): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  return axiosErr.response?.data?.detail || t("inbox.reconciliation.action_error");
}

function formatScorePercent(score: string | undefined): string {
  const num = Number(score ?? "0");
  if (!Number.isFinite(num)) return "0%";
  return `${Math.round(num * 100)}%`;
}

function getSignalLabel(signal: ReconciliationSignalRead): string {
  const knownCodes = new Set([
    "amount_exact",
    "amount_exact_rounding",
    "refund_amount_exact",
    "refund_amount_partial",
    "split_payment_pair_sum",
    "split_payment_remainder",
    "split_payment_partial",
    "date_same_day",
    "date_within_1d",
    "date_within_2d",
    "date_settlement_lag",
    "refund_date_recent",
    "refund_date_window",
    "merchant_strong_match",
    "merchant_partial_match",
    "merchant_mismatch",
    "account_exact_match",
    "account_mismatch",
    "account_unassigned",
    "source_receipt_unpaired",
    "source_manual_unpaired",
    "source_split_continuation",
    "same_day_equal_amount_ambiguity",
  ]);
  if (knownCodes.has(signal.code)) {
    return t(`inbox.reconciliation.signals.${signal.code}`);
  }
  return signal.code;
}

function getMatchKindLabel(kind: ReconciliationMatchKind): string {
  return t(`inbox.reconciliation.match_kind.${kind}`);
}

function getStatusBadge(status: ReconciliationStatus) {
  const label = t(`inbox.reconciliation.status.${status}`);
  if (status === "accepted") {
    return (
      <Badge variant="outline" className="bg-green-500/10 text-green-600 border-green-500/20">
        {label}
      </Badge>
    );
  }
  if (status === "rejected") {
    return (
      <Badge variant="outline" className="bg-destructive/10 text-destructive border-destructive/20">
        {label}
      </Badge>
    );
  }
  if (status === "unlinked") {
    return <Badge variant="secondary">{label}</Badge>;
  }
  return (
    <Badge variant="outline" className="bg-amber-500/10 text-amber-600 border-amber-500/20">
      {label}
    </Badge>
  );
}

function TransactionSideCard({
  label,
  icon,
  tx,
}: {
  label: string;
  icon: React.ReactNode;
  tx?: ReconciliationTransactionSummary | null;
}) {
  return (
    <div className="rounded-xl border bg-muted/30 p-3 space-y-1.5 min-w-0">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5 font-medium truncate">
          {icon}
          {label}
        </span>
        {tx?.provider && (
          <Badge variant="outline" className="text-[10px] h-5 shrink-0">
            {tx.provider}
          </Badge>
        )}
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold text-sm truncate">
          {tx?.merchant_name || t("inbox.list.processing_placeholder")}
        </span>
        <span className="font-bold text-sm tabular-nums shrink-0">
          {formatMoneyFixed(tx?.total_amount ?? "0.00")} {tx?.currency ?? "PLN"}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{tx?.date ? formatDate(tx.date, "PPP") : t("inbox.list.no_date")}</span>
        <span className="truncate">{tx?.account_name || t("inbox.reconciliation.no_account")}</span>
      </div>
      {tx?.note && <p className="text-xs text-muted-foreground/80 truncate">{tx.note}</p>}
    </div>
  );
}

export function ReconciliationPanel() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterValue>("pending");
  const [busyLinkId, setBusyLinkId] = useState<number | null>(null);

  const activeFilterParam = filter === "all" ? undefined : filter;

  const { data, isLoading, error } = useQuery({
    queryKey: ["reconciliation", filter],
    queryFn: () => api.getReconciliationCandidates(activeFilterParam),
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["inbox"] });
  };

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshReconciliationCandidates(activeFilterParam),
    onSuccess: () => {
      invalidateAll();
      toast.success(t("inbox.reconciliation.refresh_success"));
    },
    onError: (err) => {
      toast.error(extractErrorMessage(err));
    },
  });

  const acceptMutation = useMutation({
    mutationFn: api.acceptReconciliation,
    onMutate: (id) => setBusyLinkId(id),
    onSettled: () => setBusyLinkId(null),
    onSuccess: () => {
      invalidateAll();
      toast.success(t("inbox.reconciliation.accept_success"));
    },
    onError: (err) => {
      toast.error(extractErrorMessage(err));
    },
  });

  const rejectMutation = useMutation({
    mutationFn: api.rejectReconciliation,
    onMutate: (id) => setBusyLinkId(id),
    onSettled: () => setBusyLinkId(null),
    onSuccess: () => {
      invalidateAll();
      toast.success(t("inbox.reconciliation.reject_success"));
    },
    onError: (err) => {
      toast.error(extractErrorMessage(err));
    },
  });

  const unlinkMutation = useMutation({
    mutationFn: api.unlinkReconciliation,
    onMutate: (id) => setBusyLinkId(id),
    onSettled: () => setBusyLinkId(null),
    onSuccess: () => {
      invalidateAll();
      toast.success(t("inbox.reconciliation.unlink_success"));
    },
    onError: (err) => {
      toast.error(extractErrorMessage(err));
    },
  });

  const candidates: ReconciliationLinkRead[] = data?.candidates ?? [];
  const filterTabs: Array<{ value: FilterValue; label: string; count?: number }> = [
    { value: "pending", label: t("inbox.reconciliation.filters.pending"), count: data?.pending_count ?? 0 },
    { value: "accepted", label: t("inbox.reconciliation.filters.accepted"), count: data?.accepted_count ?? 0 },
    { value: "rejected", label: t("inbox.reconciliation.filters.rejected"), count: data?.rejected_count ?? 0 },
    { value: "unlinked", label: t("inbox.reconciliation.filters.unlinked"), count: data?.unlinked_count ?? 0 },
    { value: "all", label: t("inbox.reconciliation.filters.all") },
  ];

  return (
    <div className="flex-1 flex flex-col gap-4 overflow-hidden">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <GitCompareArrows className="h-5 w-5 text-primary" />
            {t("inbox.reconciliation.title")}
          </h2>
          <p className="text-sm text-muted-foreground">{t("inbox.reconciliation.subtitle")}</p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="self-start md:self-auto shrink-0"
        >
          <RefreshCw className={cn("h-4 w-4 mr-2", refreshMutation.isPending && "animate-spin")} />
          {t("inbox.reconciliation.refresh_button")}
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {filterTabs.map((tab) => {
          const isActive = filter === tab.value;
          return (
            <Button
              key={tab.value}
              variant={isActive ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(tab.value)}
              className="gap-1.5"
            >
              <span>{tab.label}</span>
              {typeof tab.count === "number" && (
                <Badge
                  variant={isActive ? "secondary" : "outline"}
                  className="text-[10px] h-4 px-1.5 tabular-nums"
                >
                  {tab.count}
                </Badge>
              )}
            </Button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto pr-1 space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
          </div>
        ) : error ? (
          <Card className="border-destructive/20 bg-destructive/5">
            <CardContent className="p-4 flex items-center gap-2 text-destructive text-sm">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{t("inbox.reconciliation.load_error")}</span>
            </CardContent>
          </Card>
        ) : candidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed rounded-2xl bg-card/30">
            <CheckCircle2 className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <h3 className="text-lg font-medium text-muted-foreground">
              {t("inbox.reconciliation.empty_title")}
            </h3>
            <p className="text-sm text-muted-foreground/70 max-w-md mt-1">
              {t("inbox.reconciliation.empty_description")}
            </p>
          </div>
        ) : (
          candidates.map((link) => {
            const isBusy = busyLinkId === link.id;
            const confidenceKey =
              link.confidence_tier === "high" || link.confidence_tier === "medium" || link.confidence_tier === "low"
                ? link.confidence_tier
                : "low";
            const signals = link.signals ?? [];

            return (
              <Card key={link.id} className="border-border/60 bg-card/80">
                <CardContent className="p-4 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {getStatusBadge(link.status)}
                      <Badge variant="secondary">{getMatchKindLabel(link.match_kind)}</Badge>
                      <Badge variant="outline" className="tabular-nums">
                        {t("inbox.reconciliation.score_label")}: {formatScorePercent(link.score)} (
                        {t(`inbox.reconciliation.confidence.${confidenceKey}`)})
                      </Badge>
                    </div>

                    <div className="flex items-center gap-2">
                      {link.status === "accepted" ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={isBusy}
                          onClick={() => unlinkMutation.mutate(link.id)}
                        >
                          <Link2Off className="h-4 w-4 mr-1.5" />
                          {t("inbox.reconciliation.unlink_button")}
                        </Button>
                      ) : (
                        <>
                          {link.status === "pending" && (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={isBusy}
                              onClick={() => rejectMutation.mutate(link.id)}
                            >
                              <X className="h-4 w-4 mr-1.5" />
                              {t("inbox.reconciliation.reject_button")}
                            </Button>
                          )}
                          <Button
                            size="sm"
                            disabled={isBusy}
                            onClick={() => acceptMutation.mutate(link.id)}
                          >
                            <Check className="h-4 w-4 mr-1.5" />
                            {t("inbox.reconciliation.accept_button")}
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  {(link.same_day_conflict_count ?? 0) > 1 && link.status === "pending" && (
                    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-700 dark:text-amber-300">
                      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                      <span>
                        {t("inbox.reconciliation.ambiguity_warning", {
                          count: String(link.same_day_conflict_count ?? 0),
                        })}
                      </span>
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <TransactionSideCard
                      label={t("inbox.reconciliation.bank_side_label")}
                      icon={<Landmark className="h-3.5 w-3.5" />}
                      tx={link.bank_transaction}
                    />
                    <TransactionSideCard
                      label={t("inbox.reconciliation.receipt_side_label")}
                      icon={<Receipt className="h-3.5 w-3.5" />}
                      tx={link.target_transaction}
                    />
                  </div>

                  {signals.length > 0 && (
                    <div className="space-y-1.5 pt-1">
                      <p className="text-xs font-medium text-muted-foreground">
                        {t("inbox.reconciliation.reasons_title")}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {signals.map((signal, idx) => (
                          <Badge
                            key={`${signal.code}-${idx}`}
                            variant="outline"
                            className={cn(
                              "text-xs font-normal gap-1",
                              signal.matched
                                ? "bg-primary/5 border-primary/20 text-foreground"
                                : "bg-muted/40 text-muted-foreground"
                            )}
                          >
                            <span>{getSignalLabel(signal)}</span>
                            <span className="tabular-nums opacity-70">
                              (+{formatScorePercent(signal.weight)})
                            </span>
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })
        )}
      </div>
    </div>
  );
}
