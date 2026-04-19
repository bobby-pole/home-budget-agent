import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Settings, User } from "lucide-react"
import { ThemeToggle } from "@/components/dashboard/ThemeToggle"
import { useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

const routeTitles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/budget": "Budżet",
  "/transactions": "Transakcje",
  "/inbox": "Skrzynka odbiorcza",
  "/settings": "Ustawienia",
}

function getPageTitle(pathname: string): string {
  for (const [route, title] of Object.entries(routeTitles)) {
    if (pathname === route || pathname.startsWith(`${route}/`)) {
      return title
    }
  }
  return "Smart Budget AI"
}

export function DashboardHeader() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const pageTitle = getPageTitle(location.pathname)
  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "??"

  const handleLogout = () => {
    logout()
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-card px-4 md:px-6">
      <div className="flex items-center gap-2">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-2 h-4" />
        <div>
          <h1 className="text-sm font-semibold text-foreground tracking-tight">
            {pageTitle}
          </h1>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <ThemeToggle />
        {user && <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="relative flex h-8 w-8 shrink-0 overflow-hidden rounded-full border border-border hover:opacity-80 transition-opacity">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="text-xs bg-muted">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col space-y-1">
                <p className="text-sm font-medium leading-none">{user?.email}</p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => navigate("/settings")}
              className="cursor-pointer"
            >
              <User className="mr-2 h-4 w-4" />
              Profil
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => navigate("/settings")}
              className="cursor-pointer"
            >
              <Settings className="mr-2 h-4 w-4" />
              Ustawienia
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive cursor-pointer"
              onClick={handleLogout}
            >
              Wyloguj
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>}
      </div>
    </header>
  )
}
