import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
  Settings,
  ChevronsLeft,
  ChevronsRight,
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
import { Avatar, AvatarFallback } from "@/components/ui/avatar"

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

function CollapseButton() {
  const { toggleSidebar, state } = useSidebar()

  return (
    <button
      onClick={toggleSidebar}
      className="flex items-center justify-center size-7 rounded-md text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
      aria-label="Toggle sidebar"
    >
      {state === "expanded" ? (
        <ChevronsLeft className="size-4" />
      ) : (
        <ChevronsRight className="size-4" />
      )}
    </button>
  )
}

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
      <SidebarHeader className="px-3 py-4">
        <div className={cn(
          "flex items-center gap-2.5",
          isCollapsed ? "flex-col" : "justify-between"
        )}>
          <Link to="/dashboard" className="flex items-center gap-2.5 min-w-0">
            <div className="flex items-center justify-center size-8 rounded-lg bg-primary text-primary-foreground shrink-0">
              <Wallet className="size-4" />
            </div>
            {!isCollapsed && (
              <span className="text-sm font-semibold text-sidebar-foreground tracking-tight truncate">
                Smart Budget
              </span>
            )}
          </Link>
          <CollapseButton />
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent className="px-1.5">
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
                      size="default"
                      className={cn(
                        "transition-colors",
                        isActive &&
                          "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                      )}
                    >
                      <Link to={item.href}>
                        <item.icon className="size-4" />
                        <span>{item.title}</span>
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

      <SidebarFooter className="px-1.5 pb-3">
        <SidebarMenu>
          {bottomNavItems.map((item) => {
            const isActive = pathname === item.href
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  asChild
                  isActive={isActive}
                  tooltip={item.title}
                  className={cn(
                    "transition-colors",
                    isActive &&
                      "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  )}
                >
                  <Link to={item.href}>
                    <item.icon className="size-4" />
                    <span>{item.title}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>

        <SidebarSeparator />

        <div className={cn(
          "flex items-center gap-2.5 px-2 py-1.5",
          isCollapsed && "justify-center px-0"
        )}>
          <Avatar className="size-7 shrink-0">
            <AvatarFallback className="bg-primary text-primary-foreground text-xs font-medium">
              JD
            </AvatarFallback>
          </Avatar>
          {!isCollapsed && (
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-medium text-sidebar-foreground truncate">
                Jane Doe
              </span>
              <span className="text-[11px] text-sidebar-foreground/50 truncate">
                jane@email.com
              </span>
            </div>
          )}
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
