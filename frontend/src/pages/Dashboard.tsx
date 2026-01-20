import { Header } from "@/components/dashboard/Header"
import { KPICard } from "@/components/dashboard/KpiCard"
import { ReceiptsTable } from "@/components/dashboard/ReceiptsTable"
import { SpendingChart } from "@/components/dashboard/SpendingChart"
import { UploadBox } from "@/components/dashboard/UploadBox"
import { Wallet, Receipt, Clock, PiggyBank } from "lucide-react"
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function Dashboard() {
 const { data: receipts = [], isLoading, error } = useQuery({
    queryKey: ['receipts'], // Unikalny klucz dla cache
    queryFn: api.getReceipts,
    refetchInterval: 5000, // Opcjonalnie: Odświeżaj co 5s (fajne, żeby widzieć jak status zmienia się z processing -> done)
  });

  const totalSpent = receipts.reduce((sum, r) => sum + r.total_amount, 0);
  const receiptsCount = receipts.length;
  const processingCount = receipts.filter(r => r.status === 'processing' || r.status === 'pending').length;

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="px-6 pb-8">
        {/* KPI Section */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Suma Wydatków (W miesiącu)"
            value={totalSpent.toLocaleString(undefined, { style: 'currency', currency: 'PLN' })}
            icon={Wallet}
            iconBgColor="bg-blue-100"
            iconColor="text-blue-600"
          />
          <KPICard
            title="Przesłane Paragony"
            value={receiptsCount}
            icon={Receipt}
            iconBgColor="bg-emerald-100"
            iconColor="text-emerald-600"
          />
          <KPICard
            title="Oczekujące Paragony"
            value={processingCount}
            icon={Clock}
            iconBgColor="bg-amber-100"
            iconColor="text-amber-600"
            highlight
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
        </section>

        {/* Main Content */}
        <section className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
          {/* Left Column - Receipts Table */}
          <div className="lg:col-span-3">
            <ReceiptsTable receipts={receipts} isLoading={isLoading} error={error} />
          </div>

          {/* Right Column - Spending Overview & Upload */}
          <div className="space-y-6 lg:col-span-2">
            <SpendingChart />
            <UploadBox />
          </div>
        </section>
      </main>
    </div>
  )
}
