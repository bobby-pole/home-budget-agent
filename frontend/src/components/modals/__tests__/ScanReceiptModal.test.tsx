import { render, screen, waitFor } from "../../../__tests__/test-utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ScanReceiptModal } from "../ScanReceiptModal";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getDemoQuota: vi.fn(),
    getAccounts: vi.fn(),
    scanSampleReceipt: vi.fn(),
    scanTransaction: vi.fn(),
    scanBatch: vi.fn(),
  },
}));

describe("ScanReceiptModal", () => {
  const onOpenChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAccounts).mockResolvedValue([]);
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
      total_amount: "101.74",
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

  it("queues multiple files, flags client-side invalid file, submits batch and re-uploads duplicates", async () => {
    const user = userEvent.setup({ applyAccept: false });
    vi.mocked(api.getDemoQuota).mockResolvedValue({
      is_demo: false,
      daily_limit: 999,
      used: 0,
      remaining: 999,
      can_scan: true,
    });
    vi.mocked(api.scanBatch)
      .mockResolvedValueOnce({
        import_batch_id: "batch_abc",
        total_files: 2,
        queued_count: 1,
        duplicate_count: 1,
        failed_count: 0,
        rate_limited_count: 0,
        results: [
          {
            filename: "r1.jpg",
            status: "queued",
            transaction_id: 10,
            receipt_scan_id: 20,
            job_id: 30,
          },
          {
            filename: "r_2.pdf",
            status: "duplicate",
            error_code: "DUPLICATE_FILE",
            detail: "Already imported",
          },
        ],
      })
      .mockResolvedValueOnce({
        import_batch_id: "batch_def",
        total_files: 1,
        queued_count: 1,
        duplicate_count: 0,
        failed_count: 0,
        rate_limited_count: 0,
        results: [
          {
            filename: "r_2.pdf",
            status: "queued",
            transaction_id: 11,
            receipt_scan_id: 21,
            job_id: 31,
          },
        ],
      });

    render(<ScanReceiptModal open={true} onOpenChange={onOpenChange} />);

    await screen.findByText(/Biedronka \(Katowice\)/i);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    expect(fileInput.multiple).toBe(true);

    const validImg = new File(["jpgdata"], "r1.jpg", { type: "image/jpeg" });
    const validPdf = new File(["%PDF-1.4"], "r 2.pdf", { type: "application/pdf" });
    const invalidHtml = new File(["<html></html>"], "bad.html", { type: "text/html" });

    // Trigger direct onChange with multiple files including unsupported html
    await user.upload(fileInput, [validImg, validPdf, invalidHtml]);

    expect(await screen.findByText("r1.jpg")).toBeInTheDocument();
    expect(screen.getByText("r 2.pdf")).toBeInTheDocument();
    expect(screen.getByText("bad.html")).toBeInTheDocument();
    expect(screen.getByText(/Nieobsługiwany format pliku/i)).toBeInTheDocument();

    const submitBtn = screen.getByRole("button", { name: /Wyślij paczkę \(2\)/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(api.scanBatch).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(api.scanBatch).mock.calls[0][0]).toHaveLength(2);

    expect(await screen.findByText(/Zakolejkowano 1 z 2 dokumentów/i)).toBeInTheDocument();
    const forceBtn = screen.getByRole("button", { name: /Wyślij duplikaty ponownie/i });
    await user.click(forceBtn);

    await waitFor(() => {
      expect(api.scanBatch).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(api.scanBatch).mock.calls[1][1]?.force).toBe(true);
  });
});
