import { useState, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Card, CardContent } from "@/components/ui/card"
import { Upload, FileImage, Loader2, CheckCircle2 } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

export function UploadBox() {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  // --- LOGIKA REACT QUERY ---
  const uploadMutation = useMutation({
    mutationFn: api.uploadReceipt,
    onSuccess: () => {
      // Odśwież tabelę paragonów
      queryClient.invalidateQueries({ queryKey: ["receipts"] })
      // Opcjonalnie: Tu można dodać Toast z sukcesem
    },
    onError: (error) => {
      console.error("Błąd uploadu:", error)
      alert("Wystąpił błąd podczas wysyłania pliku.")
    },
  })

  // --- OBSŁUGA ZDARZEŃ ---

  // 1. Kliknięcie w obszar
  const handleBoxClick = () => {
    if (!uploadMutation.isPending) {
      fileInputRef.current?.click()
    }
  }

  // 2. Wybór pliku z dysku
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) handleUpload(file)
  }

  // 3. Upuszczenie pliku (Drag & Drop)
  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)

    const file = event.dataTransfer.files?.[0]
    if (file) handleUpload(file)
  }

  // Pomocnicze funkcje do stylowania podczas przeciągania
  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault() // Konieczne, aby pozwolić na upuszczenie!
    setIsDragging(true)
  }
  const handleDragLeave = () => setIsDragging(false)

  // Wspólna funkcja wysyłki
  const handleUpload = (file: File) => {
    // Prosta walidacja (opcjonalnie)
    if (!file.type.startsWith("image/") && file.type !== "application/pdf") {
      alert("Proszę wgrać zdjęcie lub PDF.")
      return
    }
    uploadMutation.mutate(file)
  }

  return (
    <Card className="rounded-2xl border-0 shadow-sm">
      <CardContent className="p-6">
        {/* Ukryty input, który wykonuje brudną robotę */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          className="hidden"
          accept="image/png, image/jpeg, image/jpg, image/webp"
        />

        {/* Interaktywny obszar */}
        <div
          onClick={handleBoxClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-all duration-200",
            // Style warunkowe (korzystamy z funkcji cn)
            isDragging
              ? "border-primary bg-primary/5 scale-[0.99]"
              : "border-muted-foreground/25 bg-muted/30 hover:border-primary/50 hover:bg-accent/50",
            uploadMutation.isPending && "cursor-not-allowed opacity-70"
          )}
        >
          {/* Różne ikony w zależności od stanu */}
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 mb-4">
            {uploadMutation.isPending ? (
              <Loader2 className="h-7 w-7 text-primary animate-spin" />
            ) : uploadMutation.isSuccess ? (
              <CheckCircle2 className="h-7 w-7 text-green-500" />
            ) : (
              <Upload className="h-7 w-7 text-primary" />
            )}
          </div>

          {/* Teksty */}
          <div className="text-center space-y-1">
            {uploadMutation.isPending ? (
              <p className="text-sm font-medium text-foreground">Przetwarzanie paragonu...</p>
            ) : (
              <>
                <p className="text-sm font-medium text-foreground">
                  Upuść paragon tutaj
                </p>
                <p className="text-xs text-muted-foreground">
                  lub kliknij, aby wybrać
                </p>
              </>
            )}
          </div>

          {/* Informacja o formacie (tylko gdy nie ładujemy) */}
          {!uploadMutation.isPending && (
            <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
              <FileImage className="h-4 w-4" />
              <span>PNG, JPG, WEBP (max 10MB)</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}