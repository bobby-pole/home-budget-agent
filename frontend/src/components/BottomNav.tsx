import { useState } from "react"
import { Plus } from "lucide-react"
import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Sparkles,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import { QuickEntryDrawer } from "./QuickEntryDrawer"
import { useScanReceipt } from "@/hooks/use-scan-receipt"
import { useAddTransaction } from "@/hooks/use-add-transaction"
import { AddTransactionModal } from "@/components/dashboard/AddTransactionModal"

const leftNavItems = [
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
]

const rightNavItems = [
  {
    title: "Inbox",
    icon: Sparkles,
    href: "/inbox",
  },
  {
    title: "Trans",
    icon: ArrowLeftRight,
    href: "/transactions",
  },
]

export function BottomNav() {
  const location = useLocation()
  const pathname = location.pathname
  const [isQuickEntryOpen, setIsQuickEntryOpen] = useState(false)
  const { scanReceipt, isScanning } = useScanReceipt()
  const { isAddTxOpen, setIsAddTxOpen, openAddTransaction } = useAddTransaction()

  return (
    <>
      <nav className="md:hidden fixed bottom-0 left-0 right-0 border-t bg-background z-50">
        <div className="flex justify-between items-center h-14 px-8">
          {/* Left side: 2 links */}
          <div className="flex items-center gap-10 flex-1 justify-start">
            {leftNavItems.map((item) => {
              const isActive = pathname === item.href
              return (
                <Link
                  key={item.title}
                  to={item.href}
                  className={cn(
                    "flex flex-col items-center justify-center gap-1 text-muted-foreground transition-colors",
                    isActive && "text-primary font-medium"
                  )}
                >
                  <item.icon className={cn("size-5", isActive && "text-primary")} />
                  <span className="text-[10px] leading-none">{item.title}</span>
                </Link>
              )
            })}
          </div>

          {/* Center: FAB button */}
          <div className="relative flex justify-center">
            <button
              onClick={() => setIsQuickEntryOpen(true)}
              className="absolute -top-12 size-14 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-colors flex items-center justify-center"
            >
              <Plus className="size-6" />
            </button>
          </div>

          {/* Right side: 2 links */}
          <div className="flex items-center gap-10 flex-1 justify-end">
            {rightNavItems.map((item) => {
              const isActive = pathname === item.href
              return (
                <Link
                  key={item.title}
                  to={item.href}
                  className={cn(
                    "flex flex-col items-center justify-center gap-1 text-muted-foreground transition-colors",
                    isActive && "text-primary font-medium"
                  )}
                >
                  <item.icon className={cn("size-5", isActive && "text-primary")} />
                  <span className="text-[10px] leading-none">{item.title}</span>
                </Link>
              )
            })}
          </div>
        </div>
      </nav>

      <QuickEntryDrawer
        open={isQuickEntryOpen}
        onOpenChange={setIsQuickEntryOpen}
        onScanReceipt={scanReceipt}
        onManualEntry={openAddTransaction}
        scanPending={isScanning}
      />
      <AddTransactionModal open={isAddTxOpen} onOpenChange={setIsAddTxOpen} />
    </>
  )
}
