import { render, screen, waitFor } from "../../../__tests__/test-utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ScanReceiptModal } from "../ScanReceiptModal";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getDemoQuota: vi.fn(),
    scanSampleReceipt: vi.fn(),
    scanTransaction: vi.fn(),
  },
}));

describe("ScanReceiptModal", () => {
  const onOpenChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getDemoQuota).mockResolvedValue({
      is_demo: true,
      daily_limit: 5,
      used: 1,
      remaining: 4,
      can_scan: true,
    });
  });

  it("renders sample receipts and quota badge", async () => {
    render(<ScanReceiptModal open={true} onOpenChange={onOpenChange} />);

    expect(await screen.findByText(/Biedronka \(Katowice\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Lidl Plus \(Rybnik\)/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(api.getDemoQuota).toHaveBeenCalled();
    });

    expect(await screen.findByText(/pozostało 4 z 5/i)).toBeInTheDocument();
  });

  it("triggers scanSampleReceipt when clicking sample test button", async () => {
    const user = userEvent.setup();
    vi.mocked(api.scanSampleReceipt).mockResolvedValue({
      id: 101,
      merchant_name: "Biedronka (Wzorzec)",
      total_amount: 101.74,
      currency: "PLN",
      date: "2026-11-09",
      lines: [],
    });

    render(<ScanReceiptModal open={true} onOpenChange={onOpenChange} />);

    const testButtons = await screen.findAllByRole("button", { name: /przetestuj ten paragon/i });
    expect(testButtons.length).toBe(2);

    await user.click(testButtons[0]);

    await waitFor(() => {
      expect(api.scanSampleReceipt).toHaveBeenCalledWith("biedronka");
    });
  });

  it("renders depleted quota message when remaining is 0", async () => {
    vi.mocked(api.getDemoQuota).mockResolvedValue({
      is_demo: true,
      daily_limit: 5,
      used: 5,
      remaining: 0,
      can_scan: false,
    });

    render(<ScanReceiptModal open={true} onOpenChange={onOpenChange} />);

    expect(await screen.findByText(/limit wyczerpany/i)).toBeInTheDocument();
    expect(screen.getByText(/został wyczerpany/i)).toBeInTheDocument();
  });

  it("renders sample quota badge and disables button when sample quota is exhausted", async () => {
    vi.mocked(api.getDemoQuota).mockResolvedValue({
      is_demo: true,
      daily_limit: 5,
      used: 0,
      remaining: 5,
      can_scan: true,
      samples: {
        biedronka: { daily_limit: 2, used: 2, remaining: 0, can_scan: false },
        lidl: { daily_limit: 2, used: 1, remaining: 1, can_scan: true },
      },
    });

    render(<ScanReceiptModal open={true} onOpenChange={onOpenChange} />);

    const exhaustedElements = await screen.findAllByText(/Limit wykorzystany \(2\/2\)/i);
    expect(exhaustedElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Pozostało: 1\/2 dzisiaj/i)).toBeInTheDocument();

    const buttons = screen.getAllByRole("button");
    const biedronkaBtn = buttons.find((b) => b.textContent?.includes("Limit wykorzystany"));
    expect(biedronkaBtn).toBeDisabled();
  });
});
