import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PiggyBank } from "lucide-react";

export function BudgetPage() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-primary/10 rounded-lg">
          <PiggyBank className="h-6 w-6 text-primary" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight">Budżet</h1>
      </div>

      <Card className="rounded-2xl border-border/50 shadow-sm bg-card/50 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Planowanie Budżetu</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground italic">Work in Progress: System kopertowy i planowanie wydatków (YNAB style) pojawi się wkrótce.</p>
        </CardContent>
      </Card>
    </div>
  );
}
