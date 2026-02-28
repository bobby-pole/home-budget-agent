import { useState, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { Card } from "@/components/ui/card"
import { Upload, Loader2, CheckCircle2, Clock, Receipt, Pencil } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

interface UploadBoxProps {
  totalCount?: number;
  processingCount?: number;
  onAddManual?: () => void;
}

export function UploadBox({ totalCount = 0, processingCount = 0, onAddManual }: UploadBoxProps) {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const scanMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.scanTransaction(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] })
      toast.success("Paragon został przesłany!", {
        description: "Rozpoczynam analizę AI w tle.",
      })
      
      setTimeout(() => {
        scanMutation.reset()
      }, 5000)
    },
    onError: (error: AxiosError) => {
      if (error.response?.status !== 409) {
        console.error("Błąd uploadu:", error)
        toast.error("Wystąpił błąd podczas wysyłania pliku.", {
          description: "Spróbuj ponownie później.",
        })
      }
    },
  })

  const handleBoxClick = () => {
    if (!scanMutation.isPending) {
      fileInputRef.current?.click()
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      handleScan(file)
      event.target.value = ""
    }
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) handleScan(file)
  }

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(true)
  }
  const handleDragLeave = () => setIsDragging(false)

  const handleScan = (file: File, force = false) => {
    if (!file.type.startsWith("image/") && file.type !== "application/pdf") {
      toast.error("Nieprawidłowy format pliku.", {
        description: "Proszę wgrać zdjęcie lub PDF.",
      })
      return
    }

    scanMutation.mutate(
      { file, force },
      {
        onError: (error: AxiosError) => {
          if (error.response?.status === 409) {
            toast.warning("Wykryto duplikat!", {
              description: "Ta transakcja została już przesłana. Czy chcesz ją dodać ponownie?",
              duration: 5000,
              action: {
                label: "Tak, dodaj",
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
              scanMutation.isPending && "cursor-not-allowed opacity-70"
            )}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              className="hidden"
              accept="image/png, image/jpeg, image/jpg, image/webp"
            />
            <div className="flex h-7 w-7 lg:h-9 lg:w-9 items-center justify-center rounded-full bg-background border shadow-sm mb-1">
              {scanMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-primary animate-spin" />
              ) : scanMutation.isSuccess ? (
                <CheckCircle2 className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-green-500" />
              ) : (
                <Upload className="h-3.5 w-3.5 lg:h-4 lg:w-4 text-primary" />
              )}
            </div>
            <span className="text-[9px] lg:text-[10px] font-semibold text-foreground text-center leading-tight">
              {scanMutation.isPending ? "..." : "Zdjęcie"}
            </span>
          </div>

          {/* Separator */}
          <div className="flex flex-col items-center justify-center gap-1 shrink-0">
            <div className="h-full w-px bg-border/60" />
            <span className="text-[9px] text-muted-foreground font-medium shrink-0 py-1">lub</span>
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
              Ręcznie
            </span>
          </div>

        </div>

        {/* PRAWA STRONA: Statystyki */}
        <div className="w-[40%] lg:w-1/4 flex flex-col justify-center gap-2 py-1 pr-1">
            
            {/* Oczekujące */}
            <div className="flex flex-col">
                <span className="text-[9px] lg:text-[10px] uppercase font-bold text-muted-foreground flex items-center gap-1">
                    <Clock className="h-2.5 w-2.5" />
                    Oczekujące
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
                    Transakcji
                </span>
                <span className="text-base lg:text-lg font-semibold text-foreground mt-0.5">
                    {totalCount}
                </span>
            </div>
        </div>
      </div>
    </Card>
  )
}