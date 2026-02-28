import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
  Settings,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

const navItems = [
  {
    title: "Dash",
    icon: LayoutDashboard,
    href: "/dashboard",
  },
  {
    title: "Budget",
    icon: Wallet,
    href: "/budget",
  },
  {
    title: "Trans",
    icon: ArrowLeftRight,
    href: "/transactions",
  },
  {
    title: "Inbox",
    icon: Sparkles,
    href: "/inbox",
  },
  {
    title: "Settings",
    icon: Settings,
    href: "/settings",
  },
]

export function BottomNav() {
  const location = useLocation()
  const pathname = location.pathname

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 border-t bg-background z-50">
      <div className="flex justify-around items-center h-16">
        {navItems.map((item) => {
          const isActive = pathname === item.href
          return (
            <Link
              key={item.title}
              to={item.href}
              className={cn(
                "flex flex-col items-center justify-center gap-1 w-full h-full text-muted-foreground transition-colors",
                isActive && "text-primary font-medium"
              )}
            >
              <item.icon className={cn("size-5", isActive && "text-primary")} />
              <span className="text-[10px] leading-none">{item.title}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
