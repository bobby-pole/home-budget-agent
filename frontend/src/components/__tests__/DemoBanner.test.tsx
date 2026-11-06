import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DemoBanner } from "@/components/DemoBanner";
import { api } from "@/lib/api";
import { toast } from "sonner";

vi.mock("@/lib/api", () => ({
  api: {
    resetDemo: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe("DemoBanner", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  function renderDemoBanner() {
    return render(
      <QueryClientProvider client={queryClient}>
        <DemoBanner />
      </QueryClientProvider>
    );
  }

  it("renders notice message and reset button", () => {
    renderDemoBanner();

    expect(screen.getByText(/tryb demonstracyjny/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /zresetuj dane/i })).toBeInTheDocument();
  });

  it("calls api.resetDemo and displays success toast when clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetDemo).mockResolvedValue({ status: "ok", message: "Success" });

    renderDemoBanner();

    await user.click(screen.getByRole("button", { name: /zresetuj dane/i }));

    await waitFor(() => {
      expect(api.resetDemo).toHaveBeenCalled();
      expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/przywrócone do stanu początkowego/i));
    });
  });

  it("handles reset failure with error toast", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetDemo).mockRejectedValue(new Error("Network error"));

    renderDemoBanner();

    await user.click(screen.getByRole("button", { name: /zresetuj dane/i }));

    await waitFor(() => {
      expect(api.resetDemo).toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/nie udało się/i));
    });
  });
});
