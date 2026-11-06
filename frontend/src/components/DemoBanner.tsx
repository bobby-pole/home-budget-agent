// frontend/src/components/DemoBanner.tsx
import { useState } from "react";
import { RotateCcw, Info, Loader2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";

export function DemoBanner() {
  const [isResetting, setIsResetting] = useState(false);
  const queryClient = useQueryClient();

  const handleReset = async () => {
    try {
      setIsResetting(true);
      await api.resetDemo();
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["budget-summary"] });
      await queryClient.invalidateQueries({ queryKey: ["inbox"] });
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      await queryClient.invalidateQueries({ queryKey: ["budget-limits"] });
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast.success(t("demo.banner.reset_success"));
    } catch {
      toast.error(t("demo.banner.reset_error"));
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="w-full bg-primary/10 border-b border-primary/20 px-4 py-2 flex items-center justify-between gap-3 text-xs text-foreground z-40 shrink-0">
      <div className="flex items-center gap-2">
        <Info className="h-4 w-4 text-primary shrink-0" />
        <span className="font-medium text-foreground/90">
          {t("demo.banner.notice")}
        </span>
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleReset}
        disabled={isResetting}
        className="h-7 text-xs font-medium border-primary/30 hover:bg-primary/10 transition-colors shrink-0"
      >
        {isResetting ? (
          <>
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            {t("demo.banner.resetting")}
          </>
        ) : (
          <>
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
            {t("demo.banner.reset_button")}
          </>
        )}
      </Button>
    </div>
  );
}
