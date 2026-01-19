import { Card, CardContent } from "@/components/ui/card"
import { Upload, FileImage } from "lucide-react"

export function UploadBox() {
  return (
    <Card className="rounded-2xl border-0 shadow-sm">
      <CardContent className="p-6">
        <div className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-muted-foreground/25 bg-muted/30 p-8 transition-colors hover:border-primary/50 hover:bg-accent/50">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <Upload className="h-7 w-7 text-primary" />
          </div>
          <p className="mt-4 text-center text-sm font-medium text-foreground">
            Drag & drop your receipts here
          </p>
          <p className="mt-1 text-center text-xs text-muted-foreground">
            or click to browse files
          </p>
          <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <FileImage className="h-4 w-4" />
            <span>PNG, JPG, PDF up to 10MB</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
