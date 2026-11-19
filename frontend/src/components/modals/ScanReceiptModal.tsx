import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AutoMergePolicy, BatchDocumentUploadResponse, BatchUploadItemResult } from "@/client";
import { api } from "@/lib/api";
import { translateValidationMessage } from "@/lib/errorCodes";
import { t } from "@/lib/i18n";
import {
  formatFileSizeLabel,
  MAX_BATCH_UPLOAD_FILES,
  validateClientDocumentFile,
} from "@/lib/uploadValidation";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  Upload,
  Loader2,
  ShoppingCart,
  ShoppingBag,
  AlertCircle,
  Sparkles,
  FileText,
  X,
  CheckCircle2,
  RotateCcw,
} from "lucide-react";
import type { AxiosError } from "axios";

interface ScanReceiptModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGoToInbox?: () => void;
}

interface QueuedBatchFile {
  id: string;
  file: File;
  valid: boolean;
  errorReason?: string;
}

function getBatchResultBadgeVariant(
  status: BatchUploadItemResult["status"]
): "secondary" | "outline" | "destructive" {
  if (status === "queued") return "secondary";
  if (status === "rejected") return "destructive";
  return "outline";
}

function getBatchResultStatusLabel(status: BatchUploadItemResult["status"]): string {
  switch (status) {
    case "queued":
      return t("upload.batch_status_queued");
    case "duplicate":
      return t("upload.batch_status_duplicate");
    case "rate_limited":
      return t("upload.batch_status_rate_limited");
    default:
      return t("upload.batch_status_rejected");
  }
}

export function ScanReceiptModal({ open, onOpenChange, onGoToInbox }: ScanReceiptModalProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [activeSample, setActiveSample] = useState<"biedronka" | "lidl" | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<QueuedBatchFile[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>("auto");
  const [mergePolicy, setMergePolicy] = useState<AutoMergePolicy>("auto");
  const [batchResult, setBatchResult] = useState<BatchDocumentUploadResponse | null>(null);
  const [lastSubmittedFiles, setLastSubmittedFiles] = useState<File[]>([]);

  const { data: quota, isLoading: isQuotaLoading } = useQuery({
    queryKey: ["demo-quota"],
    queryFn: () => api.getDemoQuota(),
    enabled: open,
    staleTime: 10_000,
  });

  const isDemo = Boolean(quota?.is_demo);

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => (typeof api.getAccounts === "function" ? api.getAccounts() : Promise.resolve([])),
    enabled: open && !isDemo,
    staleTime: 30_000,
  });

  const activeAccounts = accounts.filter((acc) => acc.is_active !== false);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setQueuedFiles([]);
      setBatchResult(null);
      setLastSubmittedFiles([]);
    }
    onOpenChange(nextOpen);
  };

  const sampleMutation = useMutation({
    mutationFn: (sampleId: "biedronka" | "lidl") => api.scanSampleReceipt(sampleId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["demo-quota"] });
      toast.success(t("upload.toast_uploaded"), {
        description: data.note || t("upload.toast_uploaded_description"),
      });
      handleOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const msg = error.response?.data?.detail;
      toast.error(msg || t("upload.toast_upload_error"));
    },
    onSettled: () => {
      setActiveSample(null);
    },
  });

  const batchUploadMutation = useMutation({
    mutationFn: ({
      files,
      force,
    }: {
      files: File[];
      force?: boolean;
    }) => {
      const accountId =
        selectedAccountId !== "auto" ? Number.parseInt(selectedAccountId, 10) : undefined;
      return api.scanBatch(files, {
        force: Boolean(force),
        account_id: Number.isFinite(accountId) ? accountId : undefined,
        auto_merge_policy: mergePolicy,
      });
    },
    onSuccess: (result) => {
      setBatchResult(result);
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["demo-quota"] });
      if (result.queued_count > 0) {
        toast.success(
          t("upload.batch_summary_queued", {
            queued: String(result.queued_count),
            total: String(result.total_files),
          })
        );
      }
      // Keep only failed/invalid queued entries visible? Clear uploaded queue once result card is shown.
      setQueuedFiles([]);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const msg = error.response?.data?.detail;
      toast.error(msg || t("upload.toast_upload_error"));
    },
  });

  const handleSampleClick = (sampleId: "biedronka" | "lidl") => {
    setActiveSample(sampleId);
    sampleMutation.mutate(sampleId);
  };

  const enqueueFiles = (incoming: FileList | File[]) => {
    const incomingArray = Array.from(incoming);
    if (incomingArray.length === 0) return;
    setBatchResult(null);

    setQueuedFiles((prev) => {
      const remainingSlots = Math.max(0, MAX_BATCH_UPLOAD_FILES - prev.length);
      if (incomingArray.length > remainingSlots) {
        toast.warning(
          t("upload.batch_limit_exceeded", { maxFiles: String(MAX_BATCH_UPLOAD_FILES) })
        );
      }
      const acceptedSlice = incomingArray.slice(0, remainingSlots);
      const nextItems: QueuedBatchFile[] = acceptedSlice.map((file, idx) => {
        const validation = validateClientDocumentFile(file, isDemo);
        return {
          id: `${file.name}-${file.size}-${file.lastModified}-${prev.length + idx}`,
          file,
          valid: validation.valid,
          errorReason: validation.reason,
        };
      });
      return [...prev, ...nextItems];
    });
  };

  const handleRemoveQueuedFile = (id: string) => {
    setQueuedFiles((prev) => prev.filter((item) => item.id !== id));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      enqueueFiles(e.target.files);
      e.target.value = "";
    }
  };

  const validQueuedFiles = queuedFiles.filter((item) => item.valid).map((item) => item.file);

  const handleSubmitBatch = () => {
    if (validQueuedFiles.length === 0) return;
    setLastSubmittedFiles(validQueuedFiles);
    batchUploadMutation.mutate({ files: validQueuedFiles, force: false });
  };

  const handleForceReuploadDuplicates = () => {
    if (!batchResult || lastSubmittedFiles.length === 0) return;
    const duplicateFiles = lastSubmittedFiles.filter(
      (_, idx) => batchResult.results?.[idx]?.status === "duplicate"
    );
    if (duplicateFiles.length === 0) return;
    setLastSubmittedFiles(duplicateFiles);
    batchUploadMutation.mutate({ files: duplicateFiles, force: true });
  };

  const handleGoToInbox = () => {
    handleOpenChange(false);
    if (onGoToInbox) {
      onGoToInbox();
    } else {
      window.location.assign("/inbox");
    }
  };

  const canScan = quota?.can_scan ?? true;
  const biedronkaQuota = quota?.samples?.biedronka;
  const lidlQuota = quota?.samples?.lidl;
  const canScanBiedronka = quota?.is_demo ? (biedronkaQuota?.can_scan ?? true) : true;
  const canScanLidl = quota?.is_demo ? (lidlQuota?.can_scan ?? true) : true;
  const isBusy = sampleMutation.isPending || batchUploadMutation.isPending;
  const hasDuplicatesInResult = (batchResult?.duplicate_count ?? 0) > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl p-0 gap-0 overflow-hidden sm:rounded-2xl max-h-[90vh] flex flex-col">
        <DialogHeader className="p-5 sm:p-6 pb-4 border-b border-border/50 bg-muted/20">
          <DialogTitle className="text-xl font-bold flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {t("demo.scan_modal.title")}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground mt-1">
            {t("demo.scan_modal.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="p-5 sm:p-6 space-y-6 overflow-y-auto">
          {/* SEKTON 1: WZORCE */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                {t("demo.scan_modal.sample_section_title")}
              </span>
              <Badge variant="secondary" className="text-[11px] font-medium">
                {t("demo.scan_modal.accuracy_badge")}
              </Badge>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {/* Biedronka Card */}
              <Card className="border border-border/70 hover:border-primary/50 transition-all bg-card/80 shadow-xs">
                <CardContent className="p-4 flex flex-col justify-between h-full gap-3">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-2 font-semibold text-sm text-foreground">
                        <div className="size-7 rounded-lg bg-red-500/10 text-red-600 flex items-center justify-center shrink-0">
                          <ShoppingCart className="h-4 w-4" />
                        </div>
                        <span>{t("demo.scan_modal.sample_biedronka_title")}</span>
                      </div>
                      {quota?.is_demo && biedronkaQuota && (
                        <Badge
                          variant={canScanBiedronka ? "outline" : "destructive"}
                          className="text-[10px] px-1.5 py-0 font-normal shrink-0"
                        >
                          {canScanBiedronka
                            ? t("demo.scan_modal.sample_quota_badge", {
                                remaining: biedronkaQuota.remaining,
                                total: biedronkaQuota.daily_limit,
                              })
                            : t("demo.scan_modal.sample_quota_exhausted")}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground leading-snug">
                      {t("demo.scan_modal.sample_biedronka_desc")}
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full text-xs font-semibold hover:bg-primary hover:text-primary-foreground transition-colors"
                    disabled={isBusy || !canScanBiedronka}
                    onClick={() => handleSampleClick("biedronka")}
                  >
                    {sampleMutation.isPending && activeSample === "biedronka" ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        {t("demo.scan_modal.processing_sample")}
                      </>
                    ) : !canScanBiedronka ? (
                      t("demo.scan_modal.sample_quota_exhausted")
                    ) : (
                      t("demo.scan_modal.btn_test_sample")
                    )}
                  </Button>
                </CardContent>
              </Card>

              {/* Lidl Card */}
              <Card className="border border-border/70 hover:border-primary/50 transition-all bg-card/80 shadow-xs">
                <CardContent className="p-4 flex flex-col justify-between h-full gap-3">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-2 font-semibold text-sm text-foreground">
                        <div className="size-7 rounded-lg bg-blue-500/10 text-blue-600 flex items-center justify-center shrink-0">
                          <ShoppingBag className="h-4 w-4" />
                        </div>
                        <span>{t("demo.scan_modal.sample_lidl_title")}</span>
                      </div>
                      {quota?.is_demo && lidlQuota && (
                        <Badge
                          variant={canScanLidl ? "outline" : "destructive"}
                          className="text-[10px] px-1.5 py-0 font-normal shrink-0"
                        >
                          {canScanLidl
                            ? t("demo.scan_modal.sample_quota_badge", {
                                remaining: lidlQuota.remaining,
                                total: lidlQuota.daily_limit,
                              })
                            : t("demo.scan_modal.sample_quota_exhausted")}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground leading-snug">
                      {t("demo.scan_modal.sample_lidl_desc")}
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full text-xs font-semibold hover:bg-primary hover:text-primary-foreground transition-colors"
                    disabled={isBusy || !canScanLidl}
                    onClick={() => handleSampleClick("lidl")}
                  >
                    {sampleMutation.isPending && activeSample === "lidl" ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        {t("demo.scan_modal.processing_sample")}
                      </>
                    ) : !canScanLidl ? (
                      t("demo.scan_modal.sample_quota_exhausted")
                    ) : (
                      t("demo.scan_modal.btn_test_sample")
                    )}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>

          {/* SEPARATOR */}
          <div className="relative py-1">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-border/60" />
            </div>
            <div className="relative flex justify-center text-[10px] uppercase font-bold tracking-wider">
              <span className="bg-background px-3 text-muted-foreground">{t("upload.or")}</span>
            </div>
          </div>

          {/* SEKCJA 2: WŁASNE DOKUMENTY / PACZKA */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                {t("demo.scan_modal.custom_section_title")}
              </span>
              {quota?.is_demo && !isQuotaLoading && (
                <Badge
                  variant={canScan ? "outline" : "destructive"}
                  className="text-[11px] font-medium"
                >
                  {t("demo.quota.label")}{" "}
                  {t("demo.quota.remaining", {
                    remaining: quota.remaining,
                    total: quota.daily_limit,
                  })}
                </Badge>
              )}
            </div>

            {canScan ? (
              <div className="space-y-3">
                <div
                  onClick={() => !isBusy && fileInputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                      enqueueFiles(e.dataTransfer.files);
                    }
                  }}
                  className={cn(
                    "flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-xl transition-all cursor-pointer text-center",
                    isDragging
                      ? "bg-primary/5 border-primary scale-[0.99]"
                      : "bg-muted/20 border-border/70 hover:bg-muted/40 hover:border-primary/50",
                    isBusy && "cursor-not-allowed opacity-60"
                  )}
                >
                  <input
                    type="file"
                    multiple
                    ref={fileInputRef}
                    onChange={handleFileChange}
                    className="hidden"
                    accept="image/png, image/jpeg, image/jpg, image/webp, application/pdf, application/json, .json"
                  />
                  <div className="size-11 rounded-full bg-background border shadow-xs flex items-center justify-center mb-2.5">
                    {batchUploadMutation.isPending ? (
                      <Loader2 className="h-5 w-5 text-primary animate-spin" />
                    ) : (
                      <Upload className="h-5 w-5 text-primary" />
                    )}
                  </div>
                  <p className="text-xs sm:text-sm font-semibold text-foreground">
                    {batchUploadMutation.isPending
                      ? t("demo.scan_modal.uploading")
                      : t("demo.scan_modal.custom_upload_instruction")}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    {t("upload.batch_mode_hint", { maxFiles: String(MAX_BATCH_UPLOAD_FILES) })}
                  </p>
                </div>

                {queuedFiles.length > 0 && (
                  <div className="rounded-xl border bg-muted/20 p-3.5 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-foreground">
                        {t("upload.selected_files_title", {
                          count: String(queuedFiles.length),
                          max: String(MAX_BATCH_UPLOAD_FILES),
                        })}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-muted-foreground"
                        disabled={isBusy}
                        onClick={() => setQueuedFiles([])}
                      >
                        {t("upload.clear_queue")}
                      </Button>
                    </div>

                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                      {queuedFiles.map((item) => (
                        <div
                          key={item.id}
                          className={cn(
                            "flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs bg-background",
                            !item.valid && "border-destructive/40 bg-destructive/5"
                          )}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="truncate font-medium">{item.file.name}</span>
                            <span className="text-[11px] text-muted-foreground shrink-0">
                              {formatFileSizeLabel(item.file.size)}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {!item.valid && item.errorReason && (
                              <Badge variant="destructive" className="text-[10px] h-5">
                                {item.errorReason}
                              </Badge>
                            )}
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t("upload.remove_file")}
                              className="h-6 w-6 text-muted-foreground hover:text-foreground"
                              disabled={isBusy}
                              onClick={() => handleRemoveQueuedFile(item.id)}
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                      {!isDemo && activeAccounts.length > 0 && (
                        <div className="space-y-1">
                          <span className="text-[11px] font-medium text-muted-foreground">
                            {t("upload.account_label")}
                          </span>
                          <Select value={selectedAccountId} onValueChange={setSelectedAccountId}>
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="auto">{t("upload.account_auto")}</SelectItem>
                              {activeAccounts.map((acc) => (
                                <SelectItem key={acc.id} value={String(acc.id)}>
                                  {acc.name} ({acc.currency})
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      )}

                      <div className="space-y-1">
                        <span className="text-[11px] font-medium text-muted-foreground">
                          {t("upload.merge_policy_label")}
                        </span>
                        <Select
                          value={mergePolicy}
                          onValueChange={(v) => setMergePolicy(v as AutoMergePolicy)}
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="auto">{t("upload.merge_auto")}</SelectItem>
                            <SelectItem value="manual">{t("upload.merge_manual")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    <Button
                      type="button"
                      className="w-full"
                      disabled={isBusy || validQueuedFiles.length === 0}
                      onClick={handleSubmitBatch}
                    >
                      {batchUploadMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          {t("upload.submitting_batch", {
                            count: String(validQueuedFiles.length),
                          })}
                        </>
                      ) : (
                        t("upload.submit_batch", {
                          count: String(validQueuedFiles.length),
                        })
                      )}
                    </Button>
                  </div>
                )}

                {batchResult && (
                  <div className="rounded-xl border bg-card p-3.5 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-xs font-semibold">
                        <CheckCircle2 className="h-4 w-4 text-primary" />
                        <span>{t("upload.batch_results_title")}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {t("upload.batch_summary_queued", {
                          queued: String(batchResult.queued_count),
                          total: String(batchResult.total_files),
                        })}
                      </span>
                    </div>

                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                      {(batchResult.results ?? []).map((item, idx) => (
                        <div
                          key={`${item.filename}-${idx}`}
                          className="flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs bg-muted/20"
                        >
                          <div className="min-w-0 space-y-0.5">
                            <p className="font-medium truncate">{item.filename}</p>
                            {(item.error_code || item.detail) && (
                              <p className="text-[11px] text-muted-foreground truncate">
                                {item.error_code
                                  ? translateValidationMessage(item.error_code)
                                  : item.detail}
                              </p>
                            )}
                          </div>
                          <Badge
                            variant={getBatchResultBadgeVariant(item.status)}
                            className="text-[10px] shrink-0"
                          >
                            {getBatchResultStatusLabel(item.status)}
                          </Badge>
                        </div>
                      ))}
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {hasDuplicatesInResult && lastSubmittedFiles.length > 0 && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={batchUploadMutation.isPending}
                          onClick={handleForceReuploadDuplicates}
                          className="gap-1.5 text-xs"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          {t("upload.force_reupload_duplicates")}
                        </Button>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        onClick={handleGoToInbox}
                        className="text-xs"
                      >
                        {t("upload.go_to_inbox")}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-xs text-destructive flex items-start gap-2.5 leading-relaxed">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold mb-0.5">{t("demo.scan_modal.quota_depleted_title")}</p>
                  <p>{t("demo.quota.depleted", { total: quota?.daily_limit ?? 5 })}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
