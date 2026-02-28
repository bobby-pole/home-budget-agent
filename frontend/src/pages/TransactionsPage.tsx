import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Receipt } from "lucide-react";

export function TransactionsPage() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-primary/10 rounded-lg">
          <Receipt className="h-6 w-6 text-primary" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight">Historia Transakcji</h1>
      </div>

      <Card className="rounded-2xl border-border/50 shadow-sm bg-card/50 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Wszystkie Transakcje</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground italic">Work in Progress: Pełna historia transakcji z filtrowaniem i sortowaniem pojawi się wkrótce.</p>
        </CardContent>
      </Card>
    </div>
  );
}
