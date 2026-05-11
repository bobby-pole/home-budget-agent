import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { AxiosError } from "axios";
import { t } from "@/lib/i18n";

export function useScanReceipt() {
  const queryClient = useQueryClient();

  const scanMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.scanTransaction(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success(t("scan_receipt.toast_uploaded"), { description: t("scan_receipt.toast_uploaded_description") });
    },
    onError: (error: AxiosError) => {
      if (error.response?.status === 409) {
        toast.warning(t("scan_receipt.toast_duplicate_title"), {
          description: t("scan_receipt.toast_duplicate_description"),
          action: {
            label: t("scan_receipt.toast_duplicate_action"),
            onClick: () => {
              const formData = error.config?.data as FormData | undefined;
              const file = formData?.get("file") as File | null;
              if (file) scanMutation.mutate({ file, force: true });
            },
          },
        });
      } else {
        toast.error(t("scan_receipt.toast_error"));
      }
    },
  });

  const scanReceipt = (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast.error(t("scan_receipt.toast_invalid_file"));
      return;
    }
    scanMutation.mutate({ file });
  };

  return {
    scanReceipt,
    isScanning: scanMutation.isPending,
  };
}
