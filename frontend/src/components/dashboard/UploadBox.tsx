import { useState, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { Card } from "@/components/ui/card"
import { Upload, Loader2, CheckCircle2, Clock, Receipt, Pencil } from "lucide-react"
import { api } from "@/lib/api"
import { useOptionalAuth } from "@/context/AuthContext"
import { MAX_BATCH_UPLOAD_FILES, validateClientDocumentFile } from "@/lib/uploadValidation"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { t } from "@/lib/i18n"
import { ScanReceiptModal } from "@/components/modals/ScanReceiptModal"

interface UploadBoxProps {
  totalCount?: number;
  processingCount?: number;
  onAddManual?: () => void;
}

export function UploadBox({ totalCount = 0, processingCount = 0, onAddManual }: UploadBoxProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isScanModalOpen, setIsScanModalOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const auth = useOptionalAuth()
  const isDemo = auth?.isDemo ?? false

  const scanMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.scanTransaction(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
      queryClient.invalidateQueries({ queryKey: ["import-jobs"] })
      toast.success(t("upload.toast_uploaded"), {
        description: t("upload.toast_uploaded_description"),
      })

      setTimeout(() => {
        scanMutation.reset()
      }, 5000)
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      if (error.response?.status !== 409) {
        console.error("Upload error:", error)
        const detail = error.response?.data?.detail
        toast.error(detail || t("upload.toast_upload_error"), {
          description: detail ? undefined : t("upload.toast_upload_error_description"),
        })
      }
    },
  })

  const batchMutation = useMutation({
    mutationFn: (files: File[]) => api.scanBatch(files),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
      queryClient.invalidateQueries({ queryKey: ["import-jobs"] })
      toast.success(
        t("upload.drop_multiple_toast", { queued: String(res.queued_count) }),
        {
          description: t("upload.batch_summary_queued", {
            queued: String(res.queued_count),
            total: String(res.total_files),
          }),
        }
      )
      setTimeout(() => {
        batchMutation.reset()
      }, 5000)
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const msg = error.response?.data?.detail
      toast.error(msg || t("upload.toast_upload_error"), {
        description: t("upload.toast_upload_error_description"),
      })
    },
  })

  const isPending = scanMutation.isPending || batchMutation.isPending
  const isSuccess = scanMutation.isSuccess || batchMutation.isSuccess

  const handleBoxClick = () => {
    setIsScanModalOpen(true)
  }

  const handleFiles = (fileList: FileList | File[]) => {
    const incoming = Array.from(fileList)
    if (incoming.length === 0) return

    if (incoming.length === 1) {
      handleScan(incoming[0])
      return
    }

    if (incoming.length > MAX_BATCH_UPLOAD_FILES) {
      toast.warning(t("upload.batch_limit_exceeded", { maxFiles: String(MAX_BATCH_UPLOAD_FILES) }))
    }

    const capped = incoming.slice(0, MAX_BATCH_UPLOAD_FILES)
    const validFiles: File[] = []
    for (const file of capped) {
      const check = validateClientDocumentFile(file, isDemo)
      if (check.valid) {
        validFiles.push(file)
      } else {
        toast.error(file.name, { description: check.reason })
      }
    }

    if (validFiles.length > 0) {
      batchMutation.mutate(validFiles)
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files.length > 0) {
      handleFiles(event.target.files)
      event.target.value = ""
    }
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
    if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
      handleFiles(event.dataTransfer.files)
    }
  }

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(true)
  }
  const handleDragLeave = () => setIsDragging(false)

  const handleScan = (file: File, force = false) => {
    const check = validateClientDocumentFile(file, isDemo)
    if (!check.valid) {
      toast.error(t("upload.toast_invalid_format"), {
        description: check.reason || t("upload.toast_invalid_format_description"),
      })
      return
    }

    scanMutation.mutate(
      { file, force },
      {
        onError: (error: AxiosError) => {
          if (error.response?.status === 409) {
            toast.warning(t("upload.toast_duplicate_title"), {
              description: t("upload.toast_duplicate_description"),
              duration: 5000,
              action: {
                label: t("upload.toast_duplicate_action"),
                onClick: () => handleScan(file, true),
              },
            })
          }
        },
      }
    )
  }

  return (
    <Card className="rounded-2xl border-0 shadow-sm h-full min-h-[120px]">
      <div className="flex h-full p-2 lg:p-3 gap-2 lg:gap-4">
        {/* LEWA STRONA: Akcje dodawania */}
        <div className="w-[60%] lg:w-3/4 flex gap-2 h-full">

          {/* Upload zdjęcia */}
          <div
            onClick={handleBoxClick}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={cn(
              "flex-1 flex flex-col items-center justify-center p-2 lg:p-3 transition-all cursor-pointer rounded-xl border-2 border-dashed",
              isDragging
                ? "bg-primary/5 border-primary scale-[0.98]"
                : "bg-muted/30 border-muted-foreground/20 hover:bg-muted/50 hover:border-primary/50",
              isPending && "cursor-not-allowed opacity-70"
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
            <div className="flex h-7 w-7 lg:h-9 lg:w-9 items-center justify-center rounded-full bg-background border shadow-sm mb-1">
              {isPending ? (
                <Loader2 className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-primary animate-spin" />
              ) : isSuccess ? (
                <CheckCircle2 className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-green-500" />
              ) : (
                <Upload className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-primary" />
              )}
            </div>
            <span className="text-[9px] lg:text-[10px] font-semibold text-foreground text-center leading-tight">
              {isPending ? "..." : t("upload.photo_label")}
            </span>
          </div>

          {/* Separator */}
          <div className="flex flex-col items-center justify-center gap-1 shrink-0">
            <div className="h-full w-px bg-border/60" />
            <span className="text-[9px] text-muted-foreground font-medium shrink-0 py-1">{t("upload.or")}</span>
            <div className="h-full w-px bg-border/60" />
          </div>

          {/* Dodaj ręcznie */}
          <div
            onClick={onAddManual}
            className={cn(
              "flex-1 flex flex-col items-center justify-center p-2 lg:p-3 transition-all rounded-xl border-2 border-dashed",
              onAddManual
                ? "cursor-pointer bg-muted/30 border-muted-foreground/20 hover:bg-muted/50 hover:border-primary/50"
                : "cursor-not-allowed opacity-40 border-muted-foreground/10"
            )}
          >
            <div className="flex h-7 w-7 lg:h-9 lg:w-9 items-center justify-center rounded-full bg-background border shadow-sm mb-1">
              <Pencil className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-primary" />
            </div>
            <span className="text-[9px] lg:text-[10px] font-semibold text-foreground text-center leading-tight">
              {t("upload.manual_label")}
            </span>
          </div>

        </div>

        {/* PRAWA STRONA: Statystyki */}
        <div className="w-[40%] lg:w-1/4 flex flex-col justify-center gap-2 py-1 pr-1">

            {/* Oczekujące */}
            <div className="flex flex-col">
                <span className="text-[9px] lg:text-[10px] uppercase font-bold text-muted-foreground flex items-center gap-1">
                    <Clock className="h-2.5 w-2.5" />
                    {t("upload.pending_label")}
                </span>
                <div className="flex items-center gap-1.5 mt-0.5">
                    <span className={cn("text-lg lg:text-2xl font-bold", processingCount > 0 ? "text-amber-500" : "text-foreground")}>
                        {processingCount}
                    </span>
                    {processingCount > 0 && (
                        <div className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse shrink-0" />
                    )}
                </div>
            </div>

            <div className="h-px bg-border/50 w-full my-0.5" />

            {/* Wszystkie */}
            <div className="flex flex-col">
                <span className="text-[9px] lg:text-[10px] uppercase font-bold text-muted-foreground flex items-center gap-1">
                    <Receipt className="h-2.5 w-2.5" />
                    {t("upload.transactions_label")}
                </span>
                <span className="text-base lg:text-lg font-semibold text-foreground mt-0.5">
                    {totalCount}
                </span>
            </div>
        </div>
      </div>
      <ScanReceiptModal open={isScanModalOpen} onOpenChange={setIsScanModalOpen} />
    </Card>
  )
}
