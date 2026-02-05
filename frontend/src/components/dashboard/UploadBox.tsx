import { useState, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Card } from "@/components/ui/card"
import { Upload, Loader2, CheckCircle2, Clock, Receipt } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

interface UploadBoxProps {
  totalCount?: number;
  processingCount?: number;
}

export function UploadBox({ totalCount = 0, processingCount = 0 }: UploadBoxProps) {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const uploadMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.uploadReceipt(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["receipts"] })
      toast.success("Paragon został przesłany!", {
        description: "Rozpoczynam analizę AI w tle.",
      })
      
      setTimeout(() => {
        uploadMutation.reset()
      }, 5000)
    },
    onError: (error: any) => {
      if (error.response?.status !== 409) {
        console.error("Błąd uploadu:", error)
        toast.error("Wystąpił błąd podczas wysyłania pliku.", {
          description: "Spróbuj ponownie później.",
        })
      }
    },
  })

  const handleBoxClick = () => {
    if (!uploadMutation.isPending) {
      fileInputRef.current?.click()
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      handleUpload(file)
      event.target.value = ""
    }
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) handleUpload(file)
  }

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(true)
  }
  const handleDragLeave = () => setIsDragging(false)

  const handleUpload = (file: File, force = false) => {
    if (!file.type.startsWith("image/") && file.type !== "application/pdf") {
      toast.error("Nieprawidłowy format pliku.", {
        description: "Proszę wgrać zdjęcie lub PDF.",
      })
      return
    }

    uploadMutation.mutate(
      { file, force },
      {
        onError: (error: any) => {
          if (error.response?.status === 409) {
            toast.warning("Wykryto duplikat!", {
              description: "Ten paragon został już przesłany. Czy chcesz go dodać ponownie?",
              duration: 5000,
              action: {
                label: "Tak, dodaj",
                onClick: () => handleUpload(file, true),
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
        {/* LEWA STRONA: Upload Area */}
        <div
          onClick={handleBoxClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            "w-[60%] lg:w-3/4 flex flex-col items-center justify-center p-3 lg:p-4 transition-all cursor-pointer rounded-xl border-2 border-dashed",
            isDragging
              ? "bg-primary/5 border-primary scale-[0.98]"
              : "bg-muted/30 border-muted-foreground/20 hover:bg-muted/50 hover:border-primary/50",
            uploadMutation.isPending && "cursor-not-allowed opacity-70"
          )}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            className="hidden"
            accept="image/png, image/jpeg, image/jpg, image/webp"
          />

          <div className="flex h-8 w-8 lg:h-10 lg:w-10 items-center justify-center rounded-full bg-background border shadow-sm mb-1 lg:mb-2">
            {uploadMutation.isPending ? (
              <Loader2 className="h-4 w-4 lg:h-5 lg:w-5 text-primary animate-spin" />
            ) : uploadMutation.isSuccess ? (
              <CheckCircle2 className="h-4 w-4 lg:h-5 lg:w-5 text-green-500" />
            ) : (
              <Upload className="h-4 w-4 lg:h-5 lg:w-5 text-primary" />
            )}
          </div>
          <span className="text-[10px] lg:text-xs font-semibold text-foreground text-center">
            {uploadMutation.isPending ? "..." : "Dodaj"}
          </span>
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
                    Razem
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