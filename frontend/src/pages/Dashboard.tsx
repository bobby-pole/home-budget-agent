import { Header } from "@/components/dashboard/Header"
import { KPICard } from "@/components/dashboard/KpiCard"
import { ReceiptsTable } from "@/components/dashboard/ReceiptsTable"
import { SpendingChart } from "@/components/dashboard/SpendingChart"
import { UploadBox } from "@/components/dashboard/UploadBox"
import { Wallet, Receipt, Clock, PiggyBank } from "lucide-react"

export function Dashboard() {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="px-6 pb-8">
        {/* KPI Section */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Total Spent (This Month)"
            value="$1,250.00"
            icon={Wallet}
            iconBgColor="bg-blue-100"
            iconColor="text-blue-600"
          />
          <KPICard
            title="Receipts Processed"
            value={12}
            icon={Receipt}
            iconBgColor="bg-emerald-100"
            iconColor="text-emerald-600"
          />
          <KPICard
            title="Pending AI Analysis"
            value={2}
            icon={Clock}
            iconBgColor="bg-amber-100"
            iconColor="text-amber-600"
            highlight
          />
          <KPICard
            title="Budget Remaining"
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
            <ReceiptsTable />
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
