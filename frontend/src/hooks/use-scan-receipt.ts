import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { AxiosError } from "axios";

export function useScanReceipt() {
  const queryClient = useQueryClient();

  const scanMutation = useMutation({
    mutationFn: ({ file, force }: { file: File; force?: boolean }) =>
      api.scanTransaction(file, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Paragon przesłany!", { description: "Analiza AI w toku." });
    },
    onError: (error: AxiosError) => {
      if (error.response?.status === 409) {
        toast.warning("Duplikat!", {
          description: "Ten paragon już istnieje. Dodać mimo to?",
          action: {
            label: "Tak",
            onClick: () => {
              const formData = error.config?.data as FormData | undefined;
              const file = formData?.get("file") as File | null;
              if (file) scanMutation.mutate({ file, force: true });
            },
          },
        });
      } else {
        toast.error("Błąd wysyłania.");
      }
    },
  });

  const scanReceipt = (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast.error("Wybierz zdjęcie.");
      return;
    }
    scanMutation.mutate({ file });
  };

  return {
    scanReceipt,
    isScanning: scanMutation.isPending,
  };
}
