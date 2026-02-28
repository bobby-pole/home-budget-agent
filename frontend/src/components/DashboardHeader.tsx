import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { ThemeToggle } from "@/components/dashboard/ThemeToggle"

export function DashboardHeader() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-card px-4 md:px-6">
      <div className="flex items-center gap-2">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-2 h-4" />
        <div className="hidden md:block">
          <h1 className="text-sm font-semibold text-foreground tracking-tight">Smart Budget AI</h1>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  )
}
