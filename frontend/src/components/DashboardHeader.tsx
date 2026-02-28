import { PanelLeftIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/dashboard/ThemeToggle"
import { useSidebar } from "@/components/ui/sidebar"

export function DashboardHeader() {
  const { toggleSidebar, isMobile } = useSidebar()

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-card px-4 md:px-6">
      <div className="flex items-center gap-3">
        {isMobile && (
          <Button
            variant="ghost"
            size="icon"
            className="size-8 md:hidden text-muted-foreground"
            onClick={toggleSidebar}
          >
            <PanelLeftIcon className="size-4" />
            <span className="sr-only">Toggle sidebar</span>
          </Button>
        )}
        <div className="hidden md:block">
          <h1 className="text-sm font-semibold text-foreground">Smart Budget AI</h1>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  )
}
