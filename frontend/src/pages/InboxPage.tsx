import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Loader2, Sparkles, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { PendingVerificationList } from "@/components/inbox/PendingVerificationList";
import { VerificationCard } from "@/components/inbox/VerificationCard";
import { Card, CardContent } from "@/components/ui/card";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

export function InboxPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const isMobile = useIsMobile();

  const { data: transactions = [], isLoading, error } = useQuery({
    queryKey: ["inbox"],
    queryFn: api.getInbox,
    refetchInterval: 5000, 
  });

  // Decide which transaction to show
  const currentTransaction = transactions.find(t => t.id === selectedId) || (transactions.length > 0 && !isMobile ? transactions[0] : null);

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ["inbox"] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    if (isMobile) {
      setSelectedId(null);
    }
  };

  const showList = !isMobile || (isMobile && !selectedId);
  const showDetail = currentTransaction && (!isMobile || (isMobile && selectedId));

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] overflow-hidden">
      {/* Header - Hide on mobile if showing detail to save space */}
      {(!isMobile || !selectedId) && (
        <div className="flex items-center justify-between px-4 md:px-8 py-4 md:py-6 bg-background/50 backdrop-blur-md border-b shrink-0">
          <div className="flex items-center gap-3 md:gap-4">
            <div className="p-2 md:p-2.5 bg-primary/10 rounded-xl shadow-inner">
              <Inbox className="h-5 w-5 md:h-6 md:w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-xl md:text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">
                {t("inbox.title")}
              </h1>
              {!isMobile && (
                <p className="text-sm text-muted-foreground flex items-center gap-1.5 mt-0.5">
                  <Sparkles className="h-3 w-3 text-amber-500" />
                  {t("inbox.verify_subtitle")}
                </p>
              )}
            </div>
          </div>
          
          {transactions.length > 0 && (
            <div className="flex items-center gap-2 px-2 md:px-3 py-1 md:py-1.5 bg-primary/5 rounded-full border border-primary/10">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
              </span>
              <span className="text-[10px] md:text-xs font-bold text-primary">
                {transactions.length} {t("inbox.pending_count_label")}
              </span>
            </div>
          )}
        </div>
      )}

      <div className={cn(
        "flex-1 flex overflow-hidden bg-muted/20",
        isMobile ? "p-0" : "p-8 gap-8"
      )}>
        {/* List of pending */}
        {showList && (
          <div className={cn(
            "flex flex-col gap-4 overflow-hidden shrink-0",
            isMobile ? "w-full p-4" : "w-80"
          )}>
            {!isMobile && (
              <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground/60 px-1">
                {t("inbox.pending_section_header")}
              </h3>
            )}
            <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar">
              {isLoading ? (
                <div className="flex items-center justify-center p-12">
                  <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
                </div>
              ) : error ? (
                <Card className="border-destructive/20 bg-destructive/5">
                  <CardContent className="p-4 flex items-center gap-2 text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span className="text-xs font-medium">{t("inbox.load_error")}</span>
                  </CardContent>
                </Card>
              ) : (
                <PendingVerificationList 
                  transactions={transactions} 
                  selectedId={currentTransaction?.id}
                  onSelect={(t) => setSelectedId(t.id)}
                />
              )}
            </div>
          </div>
        )}

        {/* Main Area: Verification Card */}
        {showDetail && (
          <div className={cn(
            "flex-1 overflow-hidden",
            isMobile && "fixed inset-0 z-50 bg-background pt-[env(safe-area-inset-top)] pb-[calc(env(safe-area-inset-bottom)+64px)]"
          )}>
            <VerificationCard 
              key={currentTransaction.id}
              transaction={currentTransaction} 
              onSuccess={handleSuccess}
              onBack={isMobile ? () => setSelectedId(null) : undefined}
            />
          </div>
        )}

        {!isMobile && !currentTransaction && !isLoading && (
          <div className="flex-1 h-full flex flex-col items-center justify-center text-center p-12 bg-card/30 rounded-3xl border-2 border-dashed border-border/50">
            <div className="p-6 bg-primary/5 rounded-full mb-6">
              <Inbox className="h-12 w-12 text-primary/20" />
            </div>
            <h2 className="text-2xl font-bold text-foreground/40">{t("inbox.empty_title")}</h2>
            <p className="text-muted-foreground/50 max-w-sm mt-2">
              {t("inbox.empty_description")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
