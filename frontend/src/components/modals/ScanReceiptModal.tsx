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
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Upload, Loader2, ShoppingCart, ShoppingBag, AlertCircle, Sparkles } from "lucide-react";
import type { AxiosError } from "axios";

interface ScanReceiptModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ScanReceiptModal({ open, onOpenChange }: ScanReceiptModalProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [activeSample, setActiveSample] = useState<"biedronka" | "lidl" | null>(null);

  const { data: quota, isLoading: isQuotaLoading } = useQuery({
    queryKey: ["demo-quota"],
    queryFn: () => api.getDemoQuota(),
    enabled: open,
    staleTime: 10_000,
  });

  const sampleMutation = useMutation({
    mutationFn: (sampleId: "biedronka" | "lidl") => api.scanSampleReceipt(sampleId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["demo-quota"] });
      toast.success(t("upload.toast_uploaded"), {
        description: data.note || t("upload.toast_uploaded_description"),
      });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const msg = error.response?.data?.detail;
      toast.error(msg || t("upload.toast_upload_error"));
    },
    onSettled: () => {
      setActiveSample(null);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.scanTransaction(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["demo-quota"] });
      toast.success(t("upload.toast_uploaded"), {
        description: t("upload.toast_uploaded_description"),
      });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      if (error.response?.status === 409) {
        toast.warning(t("upload.toast_duplicate_title"), {
          description: t("upload.toast_duplicate_description"),
        });
      } else {
        const msg = error.response?.data?.detail;
        toast.error(msg || t("upload.toast_upload_error"));
      }
    },
  });

  const handleSampleClick = (sampleId: "biedronka" | "lidl") => {
    setActiveSample(sampleId);
    sampleMutation.mutate(sampleId);
  };

  const handleFileProcess = (file: File) => {
    const isImage = file.type.startsWith("image/");
    const isPdf = file.type === "application/pdf" || file.name.endsWith(".pdf");

    if (!isImage && !isPdf) {
      toast.error(t("demo.scan_modal.invalid_format"));
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      toast.error(t("demo.scan_modal.file_too_large"));
      return;
    }

    uploadMutation.mutate({ file, force: false });
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileProcess(file);
      e.target.value = "";
    }
  };

  const canScan = quota?.can_scan ?? true;
  const biedronkaQuota = quota?.samples?.biedronka;
  const lidlQuota = quota?.samples?.lidl;
  const canScanBiedronka = quota?.is_demo ? (biedronkaQuota?.can_scan ?? true) : true;
  const canScanLidl = quota?.is_demo ? (lidlQuota?.can_scan ?? true) : true;
  const isBusy = sampleMutation.isPending || uploadMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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

          {/* SEKCJA 2: WŁASNY PARAGON */}
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
                  const f = e.dataTransfer.files?.[0];
                  if (f) handleFileProcess(f);
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
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  className="hidden"
                  accept="image/png, image/jpeg, image/jpg, image/webp, application/pdf"
                />
                <div className="size-11 rounded-full bg-background border shadow-xs flex items-center justify-center mb-2.5">
                  {uploadMutation.isPending ? (
                    <Loader2 className="h-5 w-5 text-primary animate-spin" />
                  ) : (
                    <Upload className="h-5 w-5 text-primary" />
                  )}
                </div>
                <p className="text-xs sm:text-sm font-semibold text-foreground">
                  {uploadMutation.isPending ? t("demo.scan_modal.uploading") : t("demo.scan_modal.custom_upload_instruction")}
                </p>
                <p className="text-[11px] text-muted-foreground mt-1">
                  {t("demo.scan_modal.custom_upload_hint")}
                </p>
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
