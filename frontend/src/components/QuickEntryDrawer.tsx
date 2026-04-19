import { useRef } from "react"
import { Camera, Pencil } from "lucide-react"
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
import { cn } from "@/lib/utils"
import { useIsMobile } from "@/hooks/use-mobile"

interface QuickEntryDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onScanReceipt?: (file: File) => void
  onManualEntry?: () => void
  scanPending?: boolean
}

export function QuickEntryDrawer({
  open,
  onOpenChange,
  onScanReceipt,
  onManualEntry,
  scanPending = false,
}: QuickEntryDrawerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isMobile = useIsMobile()

  const handleScanClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file && onScanReceipt) {
      onScanReceipt(file)
      onOpenChange(false)
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
    <>
      <DialogHeader className="pb-4">
        <DialogTitle className="text-center text-xl">Jak chcesz dodać transakcję?</DialogTitle>
        <DialogDescription className="text-center">
          Wybierz sposób dodania nowej transakcji
        </DialogDescription>
      </DialogHeader>
      <div className="grid grid-cols-1 gap-4 max-w-md mx-auto px-4 sm:px-0">
        {/* Scan Receipt Option */}
        <Card
          className={cn(
            "cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98]",
            "border-2 hover:border-primary/50 h-[180px]",
            scanPending && "opacity-50 cursor-not-allowed"
          )}
          onClick={scanPending ? undefined : handleScanClick}
        >
          <CardContent className="p-5 sm:p-6 flex flex-col items-center justify-center text-center h-full">
            <div className="size-12 sm:size-14 rounded-full bg-primary/10 flex items-center justify-center mb-3 sm:mb-4">
              <Camera className="size-5 sm:size-6 text-primary" />
            </div>
            <h3 className="text-base sm:text-lg font-semibold mb-1 sm:mb-2">
              Zrób zdjęcie / Wgraj paragon
            </h3>
            <p className="text-muted-foreground text-xs sm:text-sm line-clamp-2">
              Sfotografuj paragon lub wybierz zdjęcie z galerii. AI automatycznie wyodrębni dane transakcji.
            </p>
            {scanPending && (
              <div className="mt-2 sm:mt-3 text-xs sm:text-sm text-amber-600">
                Przetwarzanie paragonu...
              </div>
            )}
          </CardContent>
        </Card>

        {/* Manual Entry Option */}
        <Card
          className="cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98] border-2 hover:border-primary/50 h-[180px]"
          onClick={handleManualEntryClick}
        >
          <CardContent className="p-5 sm:p-6 flex flex-col items-center justify-center text-center h-full">
            <div className="size-12 sm:size-14 rounded-full bg-primary/10 flex items-center justify-center mb-3 sm:mb-4">
              <Pencil className="size-5 sm:size-6 text-primary" />
            </div>
            <h3 className="text-base sm:text-lg font-semibold mb-1 sm:mb-2">Wpisz ręcznie</h3>
            <p className="text-muted-foreground text-xs sm:text-sm line-clamp-2">
              Wprowadź dane transakcji ręcznie - kwota, data, kategoria i inne szczegóły.
            </p>
          </CardContent>
        </Card>

        {/* Cancel Button */}
        <Button
          variant="outline"
          className="mt-4"
          onClick={() => onOpenChange(false)}
        >
          Anuluj
        </Button>
      </div>
    </>
  )

  if (isMobile) {
    return (
      <>
        <Drawer open={open} onOpenChange={onOpenChange}>
          <DrawerContent className="rounded-t-[10px] pb-6 sm:pb-8 pt-4 max-h-[96vh]">
            <div className="overflow-y-auto px-4">
              {content}
            </div>
          </DrawerContent>
        </Drawer>

        {/* Hidden file input for receipt scanning */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf"
          capture="environment"
          className="hidden"
          onChange={handleFileChange}
        />
      </>
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <div className="py-4">
            {content}
          </div>
        </DialogContent>
      </Dialog>

      {/* Hidden file input for receipt scanning */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,application/pdf"
        capture="environment"
        className="hidden"
        onChange={handleFileChange}
      />
    </>
  )
}