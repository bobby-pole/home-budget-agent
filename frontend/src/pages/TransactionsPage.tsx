import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Receipt, Upload, Loader2, FileText } from "lucide-react";
import { TransactionsTable } from "@/components/dashboard/TransactionsTable";
import { toast } from "sonner";
import { useRef } from "react";
import type { AxiosError } from "axios";
import { t } from "@/lib/i18n";

export function TransactionsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: transactions = [], isLoading, error } = useQuery({
    queryKey: ["transactions"],
    queryFn: api.getTransactions,
  });

  const importMutation = useMutation({
    mutationFn: api.importTransactions,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      let description: string;
      if (data.summary && typeof data.summary === "object" && data.summary.code === "CSV_IMPORT_COMPLETE") {
        description = t("errors.csv_import_complete", {
          imported: String(data.summary.imported),
          skipped: String(data.summary.skipped),
          filename: data.summary.filename,
        });
      } else {
        description = typeof data.summary === "string" ? data.summary : t("transactions.import_success");
      }
      toast.success(t("transactions.import_success"), {
        description,
      });
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      toast.error(t("transactions.import_error_title"), {
        description: err.response?.data?.detail || t("transactions.import_error_default"),
      });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      importMutation.mutate(file);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Receipt className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{t("transactions.page_title")}</h1>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".csv,.pdf"
            className="hidden"
          />
          <Button 
            variant="outline" 
            className="gap-2 border-dashed border-primary/50 hover:border-primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={importMutation.isPending}
          >
            {importMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            {t("transactions.import_button")}
          </Button>
          
          <Button variant="ghost" size="icon" className="text-muted-foreground" title="Eksportuj dane">
            <FileText className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="grid gap-6">
        <TransactionsTable 
          transactions={transactions} 
          isLoading={isLoading} 
          error={error} 
        />
      </div>

      {transactions.length > 0 && (
         <Card className="rounded-2xl border-border/50 bg-muted/20">
            <CardContent className="pt-6">
               <p className="text-xs text-muted-foreground text-center">
                  {t("transactions.tip")}
               </p>
            </CardContent>
         </Card>
      )}
    </div>
  );
}
