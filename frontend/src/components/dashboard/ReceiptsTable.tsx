import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreHorizontal, Store } from "lucide-react";
import type { Receipt } from "@/types";
import { cn } from "@/lib/utils";

// const receipts = [
//   {
//     id: 1,
//     merchant: "Whole Foods Market",
//     icon: ShoppingBag,
//     date: "Jan 19, 2026",
//     category: "Food",
//     status: "Done",
//     amount: 127.54,
//   },
//   {
//     id: 2,
//     merchant: "Shell Gas Station",
//     icon: Car,
//     date: "Jan 18, 2026",
//     category: "Transport",
//     status: "Done",
//     amount: 65.00,
//   },
//   {
//     id: 3,
//     merchant: "Starbucks Coffee",
//     icon: Coffee,
//     date: "Jan 17, 2026",
//     category: "Food",
//     status: "Processing",
//     amount: 8.75,
//   },
//   {
//     id: 4,
//     merchant: "Electric Company",
//     icon: Zap,
//     date: "Jan 15, 2026",
//     category: "Utilities",
//     status: "Done",
//     amount: 142.30,
//   },
//   {
//     id: 5,
//     merchant: "Target",
//     icon: Store,
//     date: "Jan 14, 2026",
//     category: "Shopping",
//     status: "Processing",
//     amount: 89.99,
//   },
// ]

const categoryColors: Record<string, string> = {
  Food: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  Transport: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Utilities: "bg-amber-100 text-amber-700 hover:bg-amber-200",
  Shopping: "bg-pink-100 text-pink-700 hover:bg-pink-200",
  Entertainment: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Health: "bg-red-100 text-red-700 hover:bg-red-200",
  Other: "bg-gray-100 text-gray-700 hover:bg-gray-200",
};

const getReceiptCategory = (receipt: Receipt): string => {
  // 1. Jeśli nie ma produktów, zwróć 'Inne'
  if (!receipt.items || receipt.items.length === 0) return "Other";

  // 2. Szukamy pierwszej nie-pustej kategorii w produktach
  const firstItemWithCategory = receipt.items.find((item) => item.category);

  // 3. Jeśli znaleziono, zwróć ją, w przeciwnym razie 'Inne'
  return firstItemWithCategory?.category || "Other";
};

interface ReceiptsTableProps {
  receipts: Receipt[];
  isLoading?: boolean;
  error?: unknown;
}

export function ReceiptsTable({
  receipts,
  isLoading,
  error,
}: ReceiptsTableProps) {
  if (error) {
    return <div className="text-red-500">Error loading receipts.</div>;
  }

  return (
    <Card className="rounded-2xl border-0 shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg font-semibold">
          Ostatnie Paragony
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="border-b border-muted">
              <TableHead className="text-muted-foreground">Sklep</TableHead>
              <TableHead className="text-muted-foreground">Data</TableHead>
              <TableHead className="text-muted-foreground">Kategoria</TableHead>
              <TableHead className="text-muted-foreground">Status</TableHead>
              <TableHead className="text-right text-muted-foreground">
                Kwota
              </TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="h-24 text-center text-muted-foreground"
                >
                  Ładowanie danych...
                </TableCell>
              </TableRow>
            ) : receipts.length === 0 ? (
              // Stan pusty (Empty State)
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="h-24 text-center text-muted-foreground"
                >
                  Brak paragonów. Wgraj pierwszy! 🧾
                </TableCell>
              </TableRow>
            ) : (
              receipts.map((receipt) => {
                const category = getReceiptCategory(receipt);
                const badgeColor =
                  categoryColors[category] || categoryColors["Other"];

                const isDone = receipt.status === "done";
                const statusColor = isDone
                  ? "bg-emerald-50/50 text-emerald-600 border-emerald-100"
                  : "bg-amber-50/50 text-amber-600 border-amber-100";

                return (
                  <TableRow
                    key={receipt.id}
                    className="border-b border-muted/50"
                  >
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                          <Store className="h-4 w-4 text-muted-foreground" />
                        </div>
                        <span className="font-medium">
                          {receipt.merchant_name}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-gray-500">
                      {new Date(receipt.date).toLocaleDateString("pl-PL")}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className={cn("rounded-md font-normal", badgeColor)}
                      >
                        {category}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={cn("rounded-md capitalize", statusColor)}
                      >
                        {receipt.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      {receipt.total_amount.toFixed(2)} {receipt.currency}
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-gray-400 hover:text-gray-600"
                          >
                            <MoreHorizontal className="h-4 w-4" />
                            <span className="sr-only">Opcje</span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem>Pokaż produkty</DropdownMenuItem>
                          <DropdownMenuItem className="text-red-600">
                            Usuń
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
