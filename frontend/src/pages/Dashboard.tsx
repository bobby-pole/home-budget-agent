import { Header } from "@/components/dashboard/Header";
import { KPICard } from "@/components/dashboard/KpiCard";
import { ReceiptsTable } from "@/components/dashboard/ReceiptsTable";
import { SpendingChart } from "@/components/dashboard/SpendingChart";
import { UploadBox } from "@/components/dashboard/UploadBox";
import { Wallet, PiggyBank, TrendingUp } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/constants";

const monthsLocative = [
  "styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu",
  "lipcu", "sierpniu", "wrześniu", "październiku", "listopadzie", "grudniu"
];

export function Dashboard() {
  const {
    data: receipts = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["receipts"],
    queryFn: api.getReceipts,
    refetchInterval: 5000,
  });

  // Obliczenia statystyk
  const totalSpent = receipts.reduce((sum, r) => sum + r.total_amount, 0);
  const receiptsCount = receipts.length;
  const processingCount = receipts.filter(
    (r) =>
      r.status === "processing" ||
      r.status === "pending" ||
      r.status === "error",
  ).length;

  const currentMonthIndex = new Date(Date.now()).getMonth();
  const monthName = monthsLocative[currentMonthIndex];

  // Logika Top Kategorii
  const categoryTotals: Record<string, number> = {};
  receipts.forEach((receipt) => {
    if (receipt.items && receipt.items.length > 0) {
      receipt.items.forEach((item) => {
        const cat = item.category || "Other";
        const val = item.price; 
        if (val > 0) categoryTotals[cat] = (categoryTotals[cat] || 0) + val;
      });
    } else if (receipt.total_amount > 0) {
      categoryTotals["Other"] = (categoryTotals["Other"] || 0) + receipt.total_amount;
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

  if (isLoading) {
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
      <main className="px-6 pb-8">
        {/* KPI Section */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title={`Suma Wydatków w ${monthName}`}
            value={totalSpent.toLocaleString(undefined, {
              style: "currency",
              currency: "PLN",
            })}
            icon={Wallet}
            iconBgColor="bg-blue-100"
            iconColor="text-blue-600"
          />

          <UploadBox
            totalCount={receiptsCount}
            processingCount={processingCount}
          />

          <KPICard
            title="Pozostały Budżet"
            value="45%"
            icon={PiggyBank}
            iconBgColor="bg-pink-100"
            iconColor="text-pink-600"
            showProgress
            progressValue={45}
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
          {/* Left Column - Receipts Table */}
          <div className="lg:col-span-3">
            <ReceiptsTable
              receipts={receipts}
              isLoading={isLoading}
              error={error}
            />
          </div>

          {/* Right Column - Spending Overview */}
          <div className="lg:col-span-2 h-full">
            <SpendingChart />
          </div>
        </section>
      </main>
    </div>
  );
}