import { Header } from "@/components/dashboard/Header";
import { KPICard } from "@/components/dashboard/KpiCard";
import { ReceiptsTable } from "@/components/dashboard/ReceiptsTable";
import { SpendingChart } from "@/components/dashboard/SpendingChart";
import { UploadBox } from "@/components/dashboard/UploadBox";
import { Button } from "@/components/ui/button";
import {
  Wallet,
  PiggyBank,
  TrendingUp,
  CalendarDays,
  Pencil,
  PlusCircle,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/constants";
import { useState, useEffect } from "react";
import { MonthlySummaryModal } from "@/components/dashboard/MonthlySummaryModal";
import { BudgetModal } from "@/components/dashboard/BudgetModal";
import { AddTransactionModal } from "@/components/dashboard/AddTransactionModal";

export function Dashboard() {
  const [isMonthlyModalOpen, setIsMonthlyModalOpen] = useState(false);
  const [isBudgetModalOpen, setIsBudgetModalOpen] = useState(false);
  const [addTxOpen, setAddTxOpen] = useState(false);

  const now = new Date();
  const curMonth = now.getMonth();
  const curYear = now.getFullYear();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "n" || e.key === "N") {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        setAddTxOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const {
    data: receipts = [],
    isLoading: isReceiptsLoading,
    error,
  } = useQuery({
    queryKey: ["receipts"],
    queryFn: api.getReceipts,
    refetchInterval: 5000,
  });

  const { data: budgetData, isLoading: isBudgetLoading } = useQuery({
    queryKey: ["budget", curYear, curMonth + 1],
    queryFn: () => api.getBudget(curYear, curMonth + 1),
  });

  // --- STATYSTYKI ---
  const totalSpent = receipts.reduce((sum, r) => {
    if (!r.date) return sum;
    const rDate = new Date(r.date);
    if (
      r.status === "done" &&
      rDate.getMonth() === curMonth &&
      rDate.getFullYear() === curYear
    ) {
      return sum + r.total_amount;
    }
    return sum;
  }, 0);

  const budgetAmount = budgetData?.amount || 0;
  const remainingBudget = budgetAmount - totalSpent;
  const budgetProgress =
    budgetAmount > 0 ? Math.min((totalSpent / budgetAmount) * 100, 100) : 0;

  const receiptsCount = receipts.length;
  const processingCount = receipts.filter(
    (r) =>
      r.status === "processing" ||
      r.status === "pending" ||
      r.status === "error",
  ).length;

  const currentMonthRaw = new Date().toLocaleString("pl-PL", { month: "long" });
  const monthName =
    currentMonthRaw.charAt(0).toUpperCase() + currentMonthRaw.slice(1);

  const categoryTotals: Record<string, number> = {};
  receipts.forEach((receipt) => {
    if (receipt.status !== "done") return;
    if (!receipt.date) return;
    const rDate = new Date(receipt.date);
    if (rDate.getMonth() === curMonth && rDate.getFullYear() === curYear) {
      receipt.items?.forEach((item) => {
        const cat = item.category || "Other";
        if (item.price > 0)
          categoryTotals[cat] = (categoryTotals[cat] || 0) + item.price;
      });
    }
  });

  let topCategoryName = "Brak";
  let topCategoryValue = 0;
  Object.entries(categoryTotals).forEach(([cat, val]) => {
    if (val > topCategoryValue) {
      topCategoryValue = val;
      topCategoryName = CATEGORY_LABELS[cat] || cat;
    }
  });

  if (isReceiptsLoading || isBudgetLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-lg animate-pulse">
          Ładowanie Twoich finansów... 💸
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="px-4 lg:px-6 pb-8">
        {/* KPI Section - 2x2 on mobile, 1x4 on desktop */}
        <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
          <KPICard
            title={`Suma Wydatków - ${monthName}`}
            value={totalSpent.toLocaleString(undefined, {
              style: "currency",
              currency: "PLN",
            })}
            icon={Wallet}
            iconBgColor="bg-blue-100"
            iconColor="text-blue-600"
            action={{
              label: "Historia wydatków",
              icon: CalendarDays,
              onClick: () => setIsMonthlyModalOpen(true),
            }}
          />

          <UploadBox
            totalCount={receiptsCount}
            processingCount={processingCount}
            onAddManual={() => setAddTxOpen(true)}
          />

          <KPICard
            title={`BUDŻET - ${monthName.toUpperCase()}`}
            value={
              <div className="flex items-center gap-1 lg:gap-2">
                <span className="truncate">
                  {budgetAmount > 0
                    ? remainingBudget.toLocaleString(undefined, {
                        style: "currency",
                        currency: "PLN",
                      })
                    : "Brak"}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5 lg:h-6 lg:w-6 rounded-full hover:bg-muted"
                  onClick={() => setIsBudgetModalOpen(true)}
                >
                  {budgetAmount > 0 ? (
                    <Pencil className="h-3 w-3 lg:h-3.5 lg:w-3.5" />
                  ) : (
                    <PlusCircle className="h-3 w-3 lg:h-3.5 lg:w-3.5" />
                  )}
                </Button>
              </div>
            }
            icon={PiggyBank}
            iconBgColor="bg-pink-100"
            iconColor="text-pink-600"
            showProgress={budgetAmount > 0}
            progressValue={budgetProgress}
            highlight={budgetAmount > 0 && remainingBudget < 0}
          />

          <KPICard
            title="Dominująca Kategoria"
            value={topCategoryName}
            icon={TrendingUp}
            iconBgColor="bg-purple-100"
            iconColor="text-purple-600"
          />
        </section>

        {/* Main Content */}
        <section className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <ReceiptsTable
              receipts={receipts}
              isLoading={isReceiptsLoading}
              error={error}
            />
          </div>
          <div className="lg:col-span-2 h-full">
            <SpendingChart />
          </div>
        </section>
      </main>

      <MonthlySummaryModal
        receipts={receipts}
        isOpen={isMonthlyModalOpen}
        onClose={() => setIsMonthlyModalOpen(false)}
      />
      <BudgetModal
        isOpen={isBudgetModalOpen}
        onClose={() => setIsBudgetModalOpen(false)}
        currentAmount={budgetAmount}
        year={curYear}
        month={curMonth + 1}
      />
      <AddTransactionModal open={addTxOpen} onOpenChange={setAddTxOpen} />
    </div>
  );
}