import { t } from "@/lib/i18n";
import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
  Landmark,
} from "lucide-react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Link, useLocation } from "react-router-dom"
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
  {
    title: "Accounts",
    icon: Landmark,
    href: "/accounts",
  },
]

// Settings has been moved to user dropdown menu
const bottomNavItems: Array<{ title: string, icon: React.ComponentType<{ className?: string }>, href: string }> = []

export function AppSidebar() {
  const location = useLocation()
  const pathname = location.pathname
  const { state } = useSidebar()
  const isCollapsed = state === "collapsed"
  const queryClient = useQueryClient()


  const { data: statusData } = useQuery({
    queryKey: ["status"],
    queryFn: api.getAppStatus,
    refetchInterval: 5000,
  })

  const { mutate: markRead } = useMutation({
    mutationFn: api.markAlertRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["status"] })
    }
  })

  useEffect(() => {
    if (statusData?.unread_alerts && statusData.unread_alerts.length > 0) {
      statusData.unread_alerts.forEach(alert => {
        let title = t("alerts.default_title");
        let description = alert.message;
        
        try {
          const payload = JSON.parse(alert.message);
          if (payload.type === "zeroed_envelope") {
            title = t("alerts.zeroed_envelope_title");
            description = t("alerts.zeroed_envelope_desc", { category: alert.category_name, remaining: payload.remaining.toFixed(2) });
          }
        } catch {
          // Fallback to raw string if not JSON
        }

        toast.warning(title, {
          description,
          duration: 10000,
        })
        markRead(alert.id)
      })
    }
  }, [statusData?.unread_alerts, markRead])

  const pendingScansCount = statusData?.inbox_items?.length || 0

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
                  {t("sidebar.smart_budget")}
                </span>
                <span className="text-[10px] text-muted-foreground truncate mt-0.5">
                  {t("sidebar.personal_finance")}
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
