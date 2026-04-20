import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  Plus,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { QuickEntryDrawer } from "@/components/QuickEntryDrawer";
import { AddTransactionModal } from "@/components/dashboard/AddTransactionModal";
import { BudgetSummaryCard } from "@/components/dashboard/BudgetSummaryCard";
import { SpendingPieChart } from "@/components/dashboard/SpendingPieChart";
import { TopEnvelopesCard } from "@/components/dashboard/TopEnvelopesCard";
import { RecentTransactionsList } from "@/components/dashboard/RecentTransactionsList";
import { useIsMobile } from "@/hooks/use-mobile";
import { useScanReceipt } from "@/hooks/use-scan-receipt";
import { useAddTransaction } from "@/hooks/use-add-transaction";
import { CATEGORY_LABELS } from "@/lib/constants";

export function Dashboard() {
  const [quickEntryOpen, setQuickEntryOpen] = useState(false);
  const { isAddTxOpen, setIsAddTxOpen, openAddTransaction } = useAddTransaction();
  const { scanReceipt, isScanning } = useScanReceipt();
  const isMobile = useIsMobile();

  const now = new Date();
  const curMonth = now.getMonth();
  const curYear = now.getFullYear();
  const monthName = now.toLocaleString("pl-PL", { month: "long" });
  const capitalizedMonth = monthName.charAt(0).toUpperCase() + monthName.slice(1);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "n" || e.key === "N") {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        setQuickEntryOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const {
    data: transactions = [],
    isLoading: isTransactionsLoading,
  } = useQuery({
    queryKey: ["transactions"],
    queryFn: api.getTransactions,
    refetchInterval: 10000,
  });

  const { data: categories = [], isLoading: isCategoriesLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const { data: budgetSummary, isLoading: isBudgetLoading } = useQuery({
    queryKey: ["budget-summary", curYear, curMonth + 1],
    queryFn: () => api.getBudgetSummary(curYear, curMonth + 1),
  });

  // --- DATA AGGREGATION ---

  const totalSpent = budgetSummary?.total_spent ?? 0;
  const totalIncome = budgetSummary?.total_income ?? 0;
  const budgetAmount = budgetSummary?.total_planned ?? 0;
  const netCashFlow = budgetSummary?.net_cash_flow ?? 0;

  // Pie Chart Data
  const pieData = (budgetSummary?.categories ?? [])
    .filter(c => c.spent > 0)
    .map(c => {
      const cat = categories.find(cat => cat.id === c.category_id);
      const displayName = CATEGORY_LABELS[cat?.name || ""] || (cat?.name ?? c.category_name);
      return {
        name: displayName,
        value: c.spent,
        color: cat?.color ?? "#9ca3af",
      };
    })
    .sort((a, b) => b.value - a.value);

  // Top Envelopes Data
  const envelopes = (budgetSummary?.categories ?? [])
    .filter(c => c.planned > 0)
    .map(c => {
      const cat = categories.find(cat => cat.id === c.category_id);
      const displayName = CATEGORY_LABELS[cat?.name || ""] || (cat?.name ?? c.category_name);
      return {
        id: c.category_id,
        name: displayName,
        spent: c.spent,
        limit: c.planned,
        color: cat?.color ?? "#3b82f6",
        icon: cat?.icon ?? "💰",
      };
    })
    .sort((a, b) => (b.spent / b.limit) - (a.spent / a.limit))
    .slice(0, 3);

  if (isTransactionsLoading || isBudgetLoading || isCategoriesLoading) {
    return (
      <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-medium text-muted-foreground animate-pulse">
            Przygotowujemy Twój pulpit...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 lg:p-8 max-w-7xl mx-auto space-y-8">
      {/* Header & Quick Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight">{capitalizedMonth} {curYear}</h1>
          <p className="text-muted-foreground font-medium">Oto podsumowanie Twoich finansów.</p>
        </div>
        {isMobile ? null : < div className="flex items-center gap-2">
          <Button
            onClick={() => setQuickEntryOpen(true)}
            className="rounded-full font-bold shadow-lg shadow-primary/20 h-11 px-6 transition-all active:scale-95"
          >
            <Plus className="mr-2 size-4" /> Dodaj transakcję
          </Button>
        </div>}
      </div>

      {/* Row 1: Summary */}
      <BudgetSummaryCard
        remaining={netCashFlow}
        planned={budgetAmount}
        spent={totalSpent}
        income={totalIncome}
        onAddTransaction={() => setQuickEntryOpen(true)}
      />

      {/* Row 2: Charts & Envelopes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <SpendingPieChart data={pieData} isLoading={isBudgetLoading} total={totalSpent} />
        <TopEnvelopesCard envelopes={envelopes} isLoading={isBudgetLoading} />
      </div>

      {/* Row 3: Recent Transactions */}
      <RecentTransactionsList transactions={transactions} categories={categories} isLoading={isTransactionsLoading} />

      {/* Modals & Drawers */}
      <QuickEntryDrawer
        open={quickEntryOpen}
        onOpenChange={setQuickEntryOpen}
        onScanReceipt={scanReceipt}
        onManualEntry={openAddTransaction}
        scanPending={isScanning}
      />
      <AddTransactionModal open={isAddTxOpen} onOpenChange={setIsAddTxOpen} />
    </div >
  );
}
