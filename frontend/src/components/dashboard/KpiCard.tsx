import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import type { LucideIcon } from "lucide-react"

interface KPICardProps {
  title: string
  value: string | number
  icon: LucideIcon
  iconBgColor: string
  iconColor: string
  showProgress?: boolean
  progressValue?: number
  highlight?: boolean
}

export function KPICard({
  title,
  value,
  icon: Icon,
  iconBgColor,
  iconColor,
  showProgress,
  progressValue,
  highlight,
}: KPICardProps) {
  return (
    <Card className={`rounded-2xl border-0 shadow-sm ${highlight ? "ring-2 ring-amber-200" : ""}`}>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">{title}</p>
            <p className={`text-2xl font-bold ${highlight ? "text-amber-600" : "text-foreground"}`}>
              {value}
            </p>
            {showProgress && progressValue !== undefined && (
              <div className="w-32">
                <Progress value={progressValue} className="h-2" />
              </div>
            )}
          </div>
          <div className={`flex h-12 w-12 items-center justify-center rounded-full ${iconBgColor}`}>
            <Icon className={`h-6 w-6 ${iconColor}`} />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
