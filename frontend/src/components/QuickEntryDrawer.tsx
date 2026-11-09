import { useState, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Camera, Pencil, Sparkles, Loader2 } from "lucide-react"
import { useOptionalAuth } from "@/context/AuthContext"
import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import {
  Drawer,
  DrawerContent,
} from "@/components/ui/drawer"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { useIsMobile } from "@/hooks/use-mobile"
import { toast } from "sonner"
import type { AxiosError } from "axios"

interface QuickEntryDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onScanReceipt?: (file: File) => void
  onOpenScanModal?: () => void
  onManualEntry?: () => void
  scanPending?: boolean
}

export function QuickEntryDrawer({
  open,
  onOpenChange,
  onScanReceipt,
  onOpenScanModal,
  onManualEntry,
  scanPending = false,
}: QuickEntryDrawerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isMobile = useIsMobile()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const auth = useOptionalAuth()
  const isDemo = auth?.isDemo ?? false
  const [activeSample, setActiveSample] = useState<"biedronka" | "lidl" | null>(null)

  const { data: quota, isLoading: isQuotaLoading } = useQuery({
    queryKey: ["demo-quota"],
    queryFn: () => api.getDemoQuota(),
    enabled: isDemo && open,
    staleTime: 10_000,
  })

  const sampleMutation = useMutation({
    mutationFn: (sampleId: "biedronka" | "lidl") => api.scanSampleReceipt(sampleId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
      queryClient.invalidateQueries({ queryKey: ["demo-quota"] })
      toast.success(t("upload.toast_uploaded"), {
        description: data.note || t("upload.toast_uploaded_description"),
      })
      onOpenChange(false)
      navigate("/inbox")
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const msg = error.response?.data?.detail
      toast.error(msg || t("upload.toast_upload_error"))
    },
    onSettled: () => {
      setActiveSample(null)
    },
  })

  const canScan = !isDemo || (quota?.can_scan ?? true)

  const handleScanClick = () => {
    if (!canScan) return
    if (!isDemo && onOpenScanModal) {
      onOpenScanModal()
      onOpenChange(false)
    } else {
      fileInputRef.current?.click()
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file && onScanReceipt) {
      onScanReceipt(file)
      onOpenChange(false)
      if (isDemo) {
        navigate("/inbox")
      }
    }
    // Reset input so the same file can be selected again
    event.target.value = ""
  }

  const handleManualEntryClick = () => {
    if (onManualEntry) {
      onManualEntry()
      onOpenChange(false)
    }
  }

  const content = (
    <div className="space-y-5">
      <DialogHeader className="pb-1 text-center">
        <DialogTitle className="text-xl font-bold">{t("quick_entry.dialog_title")}</DialogTitle>
        <DialogDescription className="text-sm text-muted-foreground">
          {t("quick_entry.dialog_description")}
        </DialogDescription>
      </DialogHeader>

      {isDemo ? (
        <div className="space-y-5">
          {/* OPCJA 1 (TRYB DEMO): Wzorcowe paragony demonstracyjne z miniaturkami */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <Sparkles className="size-3.5 text-primary" />
                {t("quick_entry.demo_samples_title")}
              </span>
              <Badge variant="secondary" className="text-[11px] font-medium">
                {t("demo.scan_modal.accuracy_badge")}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground leading-snug">
              {t("quick_entry.demo_samples_subtitle")}
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {/* Biedronka Card */}
              <Card className="border border-border/70 hover:border-primary/50 transition-all bg-card/80 overflow-hidden flex flex-col justify-between shadow-xs">
                <div className="relative h-28 w-full bg-muted/30 overflow-hidden border-b border-border/40">
                  <img
                    src="/demo_samples/biedronka_katowice.png"
                    alt={t("quick_entry.sample_biedronka_title")}
                    className="w-full h-full object-cover object-top hover:scale-105 transition-transform duration-300"
                    loading="lazy"
                  />
                  <div className="absolute top-2 left-2">
                    <Badge className="bg-red-600 text-white hover:bg-red-700 text-[10px] px-1.5 py-0.5 shadow-xs">
                      {t("quick_entry.badge_biedronka")}
                    </Badge>
                  </div>
                </div>
                <CardContent className="p-3.5 flex flex-col justify-between gap-3 flex-1">
                  <div>
                    <h4 className="text-sm font-semibold text-foreground">
                      {t("quick_entry.sample_biedronka_title")}
                    </h4>
                    <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                      {t("quick_entry.sample_biedronka_desc")}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="w-full text-xs font-semibold"
                    disabled={sampleMutation.isPending}
                    onClick={() => {
                      setActiveSample("biedronka")
                      sampleMutation.mutate("biedronka")
                    }}
                  >
                    {sampleMutation.isPending && activeSample === "biedronka" ? (
                      <>
                        <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                        {t("quick_entry.processing_sample")}
                      </>
                    ) : (
                      t("quick_entry.btn_test_sample")
                    )}
                  </Button>
                </CardContent>
              </Card>

              {/* Lidl Card */}
              <Card className="border border-border/70 hover:border-primary/50 transition-all bg-card/80 overflow-hidden flex flex-col justify-between shadow-xs">
                <div className="relative h-28 w-full bg-muted/30 overflow-hidden border-b border-border/40">
                  <img
                    src="/demo_samples/lidl_rybnik.png"
                    alt={t("quick_entry.sample_lidl_title")}
                    className="w-full h-full object-cover object-top hover:scale-105 transition-transform duration-300"
                    loading="lazy"
                  />
                  <div className="absolute top-2 left-2">
                    <Badge className="bg-blue-600 text-white hover:bg-blue-700 text-[10px] px-1.5 py-0.5 shadow-xs">
                      {t("quick_entry.badge_lidl")}
                    </Badge>
                  </div>
                </div>
                <CardContent className="p-3.5 flex flex-col justify-between gap-3 flex-1">
                  <div>
                    <h4 className="text-sm font-semibold text-foreground">
                      {t("quick_entry.sample_lidl_title")}
                    </h4>
                    <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                      {t("quick_entry.sample_lidl_desc")}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="w-full text-xs font-semibold"
                    disabled={sampleMutation.isPending}
                    onClick={() => {
                      setActiveSample("lidl")
                      sampleMutation.mutate("lidl")
                    }}
                  >
                    {sampleMutation.isPending && activeSample === "lidl" ? (
                      <>
                        <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                        {t("quick_entry.processing_sample")}
                      </>
                    ) : (
                      t("quick_entry.btn_test_sample")
                    )}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Separator */}
          <div className="relative py-1">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-border/60" />
            </div>
            <div className="relative flex justify-center text-[10px] uppercase font-bold tracking-wider">
              <span className="bg-background px-3 text-muted-foreground">{t("upload.or")}</span>
            </div>
          </div>

          {/* OPCJA 2 i 3: Własne zdjęcie oraz Wpis ręczny */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {/* Własne zdjęcie / PDF */}
            <Card
              className={cn(
                "border-2 transition-all flex flex-col justify-between",
                canScan && !scanPending
                  ? "cursor-pointer hover:border-primary/50 hover:scale-[1.01] active:scale-[0.99]"
                  : "opacity-60 cursor-not-allowed border-dashed"
              )}
              onClick={canScan && !scanPending ? handleScanClick : undefined}
            >
              <CardContent className="p-4 flex flex-col items-center justify-center text-center h-full">
                <div className="size-10 rounded-full bg-primary/10 flex items-center justify-center mb-2">
                  <Camera className="size-5 text-primary" />
                </div>
                <h4 className="text-sm font-semibold mb-1">{t("quick_entry.scan_title")}</h4>
                {quota?.is_demo && !isQuotaLoading && (
                  <Badge
                    variant={canScan ? "outline" : "destructive"}
                    className="text-[10px] font-medium mb-2"
                  >
                    {canScan
                      ? t("quick_entry.quota_remaining", { remaining: quota.remaining, total: quota.daily_limit })
                      : t("quick_entry.quota_depleted")}
                  </Badge>
                )}
                <p className="text-muted-foreground text-xs line-clamp-2">
                  {canScan ? t("quick_entry.scan_description") : t("quick_entry.quota_depleted_hint")}
                </p>
                {scanPending && (
                  <div className="mt-2 text-xs text-amber-600 flex items-center gap-1">
                    <Loader2 className="size-3.5 animate-spin" />
                    {t("quick_entry.scan_pending")}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Wpisz ręcznie */}
            <Card
              className="border-2 hover:border-primary/50 hover:scale-[1.01] active:scale-[0.99] cursor-pointer transition-all flex flex-col justify-between"
              onClick={handleManualEntryClick}
            >
              <CardContent className="p-4 flex flex-col items-center justify-center text-center h-full">
                <div className="size-10 rounded-full bg-primary/10 flex items-center justify-center mb-2">
                  <Pencil className="size-5 text-primary" />
                </div>
                <h4 className="text-sm font-semibold mb-1">{t("quick_entry.manual_title")}</h4>
                <p className="text-muted-foreground text-xs line-clamp-2">
                  {t("quick_entry.manual_description")}
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        /* TRYB STANDARDOWY (NIE-DEMO) */
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-lg mx-auto">
          {/* Scan Receipt Option */}
          <Card
            className={cn(
              "cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98]",
              "border-2 hover:border-primary/50 min-h-[160px]",
              scanPending && "opacity-50 cursor-not-allowed"
            )}
            onClick={scanPending ? undefined : handleScanClick}
          >
            <CardContent className="p-5 flex flex-col items-center justify-center text-center h-full">
              <div className="size-12 rounded-full bg-primary/10 flex items-center justify-center mb-3">
                <Camera className="size-6 text-primary" />
              </div>
              <h3 className="text-base font-semibold mb-1">
                {t("quick_entry.scan_title")}
              </h3>
              <p className="text-muted-foreground text-xs line-clamp-2">
                {t("quick_entry.scan_description")}
              </p>
              {scanPending && (
                <div className="mt-2 text-xs text-amber-600 flex items-center gap-1">
                  <Loader2 className="size-3.5 animate-spin" />
                  {t("quick_entry.scan_pending")}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Manual Entry Option */}
          <Card
            className="cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98] border-2 hover:border-primary/50 min-h-[160px]"
            onClick={handleManualEntryClick}
          >
            <CardContent className="p-5 flex flex-col items-center justify-center text-center h-full">
              <div className="size-12 rounded-full bg-primary/10 flex items-center justify-center mb-3">
                <Pencil className="size-6 text-primary" />
              </div>
              <h3 className="text-base font-semibold mb-1">{t("quick_entry.manual_title")}</h3>
              <p className="text-muted-foreground text-xs line-clamp-2">
                {t("quick_entry.manual_description")}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Cancel Button */}
      <div className="flex justify-center pt-1">
        <Button
          variant="outline"
          size="sm"
          className="w-full sm:w-auto px-8"
          onClick={() => onOpenChange(false)}
        >
          {t("quick_entry.cancel_button")}
        </Button>
      </div>
    </div>
  )

  if (isMobile) {
    return (
      <>
        <Drawer open={open} onOpenChange={onOpenChange}>
          <DrawerContent className="rounded-t-[14px] pb-6 pt-3 max-h-[92vh]">
            <div className="overflow-y-auto px-4">
              {content}
            </div>
          </DrawerContent>
        </Drawer>

        {/* Hidden file input for receipt scanning */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf,application/json,.json"
          className="hidden"
          onChange={handleFileChange}
        />
      </>
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className={cn("p-0 overflow-hidden sm:rounded-2xl max-h-[90vh] flex flex-col", isDemo ? "sm:max-w-2xl" : "sm:max-w-lg")}>
          <div className="p-6 overflow-y-auto">
            {content}
          </div>
        </DialogContent>
      </Dialog>

      {/* Hidden file input for receipt scanning */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,application/pdf,application/json,.json"
        className="hidden"
        onChange={handleFileChange}
      />
    </>
  )
}
