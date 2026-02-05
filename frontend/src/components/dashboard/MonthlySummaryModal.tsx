import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Receipt } from "@/types";
import { CalendarDays } from "lucide-react";

interface MonthlySummaryModalProps {
  receipts: Receipt[];
  isOpen: boolean;
  onClose: () => void;
}

export function MonthlySummaryModal({
  receipts,
  isOpen,
  onClose,
}: MonthlySummaryModalProps) {
  // Aggregate data by Year-Month
  const monthlyData: Record<string, number> = {};

  receipts.forEach((r) => {
    if (r.date && (r.status === "done" || r.total_amount > 0)) {
      const date = new Date(r.date);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
      monthlyData[key] = (monthlyData[key] || 0) + r.total_amount;
    }
  });

  // Sort by date descending
  const sortedMonths = Object.entries(monthlyData).sort((a, b) =>
    b[0].localeCompare(a[0])
  );

  const formatMonthKey = (key: string) => {
    const [year, month] = key.split("-");
    const date = new Date(Number(year), Number(month) - 1);
    const monthName = date.toLocaleString("pl-PL", { month: "long" });
    return `${monthName.charAt(0).toUpperCase() + monthName.slice(1)} ${year}`;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarDays className="h-5 w-5 text-primary" />
            Podsumowanie Miesięczne
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="mt-4 h-[300px] pr-4">
          <div className="space-y-3">
            {sortedMonths.length > 0 ? (
              sortedMonths.map(([key, amount]) => (
                <div
                  key={key}
                  className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-muted"
                >
                  <span className="font-medium text-sm">
                    {formatMonthKey(key)}
                  </span>
                  <span className="font-bold text-primary">
                    {amount.toLocaleString("pl-PL", {
                      style: "currency",
                      currency: "PLN",
                    })}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-center text-muted-foreground text-sm py-10">
                Brak danych do wyświetlenia.
              </p>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
