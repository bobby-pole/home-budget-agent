import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { MoreHorizontal, Store, Coffee, Car, Zap, ShoppingBag } from "lucide-react"

const receipts = [
  {
    id: 1,
    merchant: "Whole Foods Market",
    icon: ShoppingBag,
    date: "Jan 19, 2026",
    category: "Food",
    status: "Done",
    amount: 127.54,
  },
  {
    id: 2,
    merchant: "Shell Gas Station",
    icon: Car,
    date: "Jan 18, 2026",
    category: "Transport",
    status: "Done",
    amount: 65.00,
  },
  {
    id: 3,
    merchant: "Starbucks Coffee",
    icon: Coffee,
    date: "Jan 17, 2026",
    category: "Food",
    status: "Processing",
    amount: 8.75,
  },
  {
    id: 4,
    merchant: "Electric Company",
    icon: Zap,
    date: "Jan 15, 2026",
    category: "Utilities",
    status: "Done",
    amount: 142.30,
  },
  {
    id: 5,
    merchant: "Target",
    icon: Store,
    date: "Jan 14, 2026",
    category: "Shopping",
    status: "Processing",
    amount: 89.99,
  },
]

const categoryColors: Record<string, string> = {
  Food: "bg-emerald-100 text-emerald-700",
  Transport: "bg-blue-100 text-blue-700",
  Utilities: "bg-amber-100 text-amber-700",
  Shopping: "bg-pink-100 text-pink-700",
}

const statusColors: Record<string, string> = {
  Done: "bg-emerald-100 text-emerald-700",
  Processing: "bg-amber-100 text-amber-700",
}

export function ReceiptsTable() {
  return (
    <Card className="rounded-2xl border-0 shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg font-semibold">Recent Receipts</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="border-b border-muted">
              <TableHead className="text-muted-foreground">Merchant</TableHead>
              <TableHead className="text-muted-foreground">Date</TableHead>
              <TableHead className="text-muted-foreground">Category</TableHead>
              <TableHead className="text-muted-foreground">Status</TableHead>
              <TableHead className="text-right text-muted-foreground">Amount</TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {receipts.map((receipt) => {
              const IconComponent = receipt.icon
              return (
                <TableRow key={receipt.id} className="border-b border-muted/50">
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                        <IconComponent className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <span className="font-medium">{receipt.merchant}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{receipt.date}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className={categoryColors[receipt.category]}>
                      {receipt.category}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className={statusColors[receipt.status]}>
                      {receipt.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-semibold">
                    ${receipt.amount.toFixed(2)}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreHorizontal className="h-4 w-4" />
                          <span className="sr-only">Open menu</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem>View Details</DropdownMenuItem>
                        <DropdownMenuItem>Edit</DropdownMenuItem>
                        <DropdownMenuItem className="text-destructive">Delete</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
