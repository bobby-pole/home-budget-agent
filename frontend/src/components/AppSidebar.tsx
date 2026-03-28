import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
  Settings,
  LogOut,
  User,
} from "lucide-react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"

import { cn } from "@/lib/utils"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

const mainNavItems = [
  {
    title: "Dashboard",
    icon: LayoutDashboard,
    href: "/dashboard",
  },
  {
    title: "Budget",
    icon: Wallet,
    href: "/budget",
  },
  {
    title: "Transactions",
    icon: ArrowLeftRight,
    href: "/transactions",
  },
  {
    title: "AI Inbox",
    icon: Sparkles,
    href: "/inbox",
  },
]

const bottomNavItems = [
  {
    title: "Settings",
    icon: Settings,
    href: "/settings",
  },
]

export function AppSidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const pathname = location.pathname
  const { state } = useSidebar()
  const isCollapsed = state === "collapsed"

  const { data: transactions = [] } = useQuery({
    queryKey: ["transactions"],
    queryFn: api.getTransactions,
  })

  const pendingScansCount = transactions.filter(
    (t) => t.receipt_scan && t.receipt_scan.status !== "done"
  ).length

  const handleLogout = () => {
    logout()
    navigate("/login")
  }

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "??"

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="px-2 py-4">
        <div className={cn(
          "flex items-center",
          isCollapsed ? "justify-center" : "px-2"
        )}>
          <Link to="/dashboard" className="flex items-center gap-2.5 min-w-0">
            <div className="flex items-center justify-center size-9 rounded-lg bg-primary text-primary-foreground shrink-0 shadow-sm transition-all">
              <Wallet className="size-5" />
            </div>
            {!isCollapsed && (
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-semibold text-sidebar-foreground tracking-tight truncate leading-none">
                  Smart Budget
                </span>
                <span className="text-[10px] text-muted-foreground truncate mt-0.5">
                  Personal Finance
                </span>
              </div>
            )}
          </Link>
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent className="px-2">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {mainNavItems.map((item) => {
                const isActive = pathname === item.href
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      size="lg"
                      className={cn(
                        "transition-all duration-200",
                        isActive &&
                          "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
                        isCollapsed && "justify-center"
                      )}
                    >
                      <Link to={item.href}>
                        <item.icon className={cn("shrink-0", isCollapsed ? "size-5" : "size-4")} />
                        {!isCollapsed && <span>{item.title}</span>}
                      </Link>
                    </SidebarMenuButton>
                    {item.title === "AI Inbox" && pendingScansCount > 0 && (
                      <SidebarMenuBadge className="bg-destructive text-destructive-foreground">
                        {pendingScansCount}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-2 pb-3">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {bottomNavItems.map((item) => {
                const isActive = pathname === item.href
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      size="lg"
                      className={cn(
                        "transition-all duration-200",
                        isActive &&
                          "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
                        isCollapsed && "justify-center"
                      )}
                    >
                      <Link to={item.href}>
                        <item.icon className={cn("shrink-0", isCollapsed ? "size-5" : "size-4")} />
                        {!isCollapsed && <span>{item.title}</span>}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>

            <SidebarSeparator className="my-2" />

            <SidebarMenu>
              <SidebarMenuItem>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <SidebarMenuButton
                      size="lg"
                      className={cn(
                        "data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground transition-all duration-200",
                        isCollapsed && "justify-center"
                      )}
                    >
                      <Avatar className="size-8 shrink-0 rounded-lg shadow-sm">
                        <AvatarFallback className="bg-primary text-primary-foreground text-xs font-black rounded-lg">
                          {initials}
                        </AvatarFallback>
                      </Avatar>
                      {!isCollapsed && (
                        <div className="grid flex-1 text-left text-sm leading-tight ml-2">
                          <span className="truncate font-semibold text-sidebar-foreground">
                            {user?.email?.split('@')[0]}
                          </span>
                          <span className="truncate text-[10px] text-muted-foreground">
                            {user?.email}
                          </span>
                        </div>
                      )}
                    </SidebarMenuButton>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                    side="right"
                    align="end"
                    sideOffset={4}
                  >
                    <DropdownMenuLabel className="p-0 font-normal">
                      <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                        <Avatar className="h-8 w-8 rounded-lg">
                          <AvatarFallback className="bg-primary text-primary-foreground rounded-lg">
                            {initials}
                          </AvatarFallback>
                        </Avatar>
                        <div className="grid flex-1 text-left text-sm leading-tight">
                          <span className="truncate font-semibold">{user?.email?.split('@')[0]}</span>
                          <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
                        </div>
                      </div>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => navigate("/settings")} className="cursor-pointer">
                      <User className="mr-2 h-4 w-4" />
                      Profil
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => navigate("/settings")} className="cursor-pointer">
                      <Settings className="mr-2 h-4 w-4" />
                      Ustawienia
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem 
                      onClick={handleLogout} 
                      className="text-destructive focus:text-destructive cursor-pointer"
                    >
                      <LogOut className="mr-2 h-4 w-4" />
                      Wyloguj się
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
