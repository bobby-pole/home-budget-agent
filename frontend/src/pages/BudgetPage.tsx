import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ReadyToAssignBanner } from "@/components/budget/ReadyToAssignBanner";
import { EnvelopeGroupList, type EnvelopeItem } from "@/components/budget/EnvelopeGroupList";
import { AddIncomeModal } from "@/components/budget/AddIncomeModal";
import { AllocationDrawer } from "@/components/budget/AllocationDrawer";
import { CATEGORY_LABELS } from "@/lib/constants";

export function BudgetPage() {
  const [isAddIncomeOpen, setIsAddIncomeOpen] = useState(false);
  const [selectedEnvelope, setSelectedEnvelope] = useState<EnvelopeItem | null>(null);

  const now = new Date();
  const curMonth = now.getMonth();
  const curYear = now.getFullYear();
  const monthName = now.toLocaleString("pl-PL", { month: "long" });
  const capitalizedMonth = monthName.charAt(0).toUpperCase() + monthName.slice(1);

  const { data: categories = [], isLoading: isCategoriesLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: api.getCategories,
  });

  const { data: budgetSummary, isLoading: isBudgetLoading } = useQuery({
    queryKey: ["budget-summary", curYear, curMonth + 1],
    queryFn: () => api.getBudgetSummary(curYear, curMonth + 1),
  });

  const isLoading = isCategoriesLoading || isBudgetLoading;

  const totalIncome = budgetSummary?.total_income ?? 0;
  const totalPlanned = budgetSummary?.total_planned ?? 0;

  const envelopes: EnvelopeItem[] = categories.map(cat => {
    const summaryItem = (budgetSummary?.categories ?? []).find(c => c.category_id === cat.id);
    const displayName = cat.is_system ? (CATEGORY_LABELS[cat.name] || cat.name) : cat.name;
    return {
      categoryId: cat.id,
      categoryName: displayName,
      planned: summaryItem?.planned ?? 0,
      spent: summaryItem?.spent ?? 0,
      remaining: summaryItem?.remaining ?? 0,
      icon: cat.icon ?? "💰",
      color: cat.color ?? "#3b82f6",
    };
  }).sort((a, b) => {
    if (b.planned !== a.planned) {
      return b.planned - a.planned;
    }
    return a.categoryName.localeCompare(b.categoryName);
  });

  return (
    <div className="p-4 lg:p-8 max-w-7xl mx-auto space-y-8 pb-24">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight">Budżet na {capitalizedMonth} {curYear}</h1>
          <p className="text-muted-foreground font-medium">Zaplanuj każdą złotówkę według metody kopertowej.</p>
        </div>
      </div>

      <ReadyToAssignBanner 
        totalIncome={totalIncome} 
        totalPlanned={totalPlanned} 
        onAddIncome={() => setIsAddIncomeOpen(true)} 
      />

      <EnvelopeGroupList 
        items={envelopes} 
        isLoading={isLoading} 
        onEnvelopeClick={setSelectedEnvelope}
        year={curYear}
        month={curMonth + 1}
      />

      <AddIncomeModal 
        open={isAddIncomeOpen} 
        onOpenChange={setIsAddIncomeOpen} 
      />

      <AllocationDrawer 
        open={!!selectedEnvelope} 
        onOpenChange={(open) => !open && setSelectedEnvelope(null)}
        categoryId={selectedEnvelope?.categoryId ?? null}
        categoryName={selectedEnvelope?.categoryName ?? ""}
        categoryIcon={selectedEnvelope?.icon ?? "💰"}
        currentPlanned={selectedEnvelope?.planned ?? 0}
        year={curYear}
        month={curMonth + 1}
      />
    </div>
  );
}
