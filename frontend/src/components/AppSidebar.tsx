import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

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

// Settings has been moved to user dropdown menu
const bottomNavItems: Array<{ title: string, icon: React.ComponentType<{ className?: string }>, href: string }> = []

export function AppSidebar() {
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
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
