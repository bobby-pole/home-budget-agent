import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Button } from "@/components/ui/button"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface KPICardProps {
  title: string
  value: ReactNode
  icon: LucideIcon
  iconBgColor: string
  iconColor: string
  showProgress?: boolean
  progressValue?: number
  highlight?: boolean
  action?: {
    label: string
    icon: LucideIcon
    onClick: () => void
  }
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
  action,
}: KPICardProps) {
  return (
    <Card className={`rounded-2xl border border-border/50 shadow-sm relative overflow-hidden transition-all hover:shadow-md ${highlight ? "ring-2 ring-red-500/20 bg-red-500/5" : "bg-card/50 backdrop-blur-sm"}`}>
      <CardContent className="p-4 lg:p-6 h-full flex flex-col justify-between min-h-[130px] lg:min-h-[140px]">
        <div className="flex items-start justify-between">
          <div className="space-y-1 min-w-0">
            <p className="text-[10px] lg:text-xs font-bold uppercase tracking-wider text-muted-foreground truncate">{title}</p>
            <div className="flex items-center gap-1 lg:gap-2">
                <div className={`text-base lg:text-2xl font-bold truncate ${highlight ? "text-red-600" : "text-foreground"}`}>
                {value}
                </div>
            </div>
          </div>
          <div className={`flex h-10 w-10 lg:h-12 lg:w-12 items-center justify-center rounded-full shrink-0 ${iconBgColor}`}>
            <Icon className={`h-5 w-5 lg:h-6 lg:w-6 ${iconColor}`} />
          </div>
        </div>

        <div className="space-y-2 mt-4">
            {showProgress && progressValue !== undefined && (
                <div className="w-full space-y-1">
                    <div className="flex justify-between text-[10px] font-bold uppercase text-muted-foreground">
                        <span>Zużycie</span>
                        <span className={highlight ? "text-red-600" : ""}>{Math.round(progressValue)}%</span>
                    </div>
                    <Progress value={progressValue} className={cn("h-2 lg:h-3", highlight ? "bg-red-100" : "")} />
                </div>
            )}
            
            {!showProgress && action && (
                <Button 
                    variant="secondary" 
                    size="sm" 
                    className="h-7 lg:h-8 px-3 lg:px-4 text-[10px] lg:text-xs font-bold bg-primary/10 text-primary hover:bg-primary/20 rounded-full transition-colors w-full lg:w-auto"
                    onClick={action.onClick}
                >
                    <action.icon className="mr-2 h-3.5 w-3.5" />
                    {action.label}
                </Button>
            )}
        </div>
      </CardContent>
    </Card>
  )
}
