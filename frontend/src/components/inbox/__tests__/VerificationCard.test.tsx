import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { VerificationCard } from "@/components/inbox/VerificationCard";
import type { TransactionRead } from "@/client";

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: vi.fn().mockRejectedValue(new Error("no image")),
  },
  api: {
    getCategories: vi.fn().mockResolvedValue([
      { id: 1, name: "Food", is_system: true, color: "#10b981", icon: "utensils" },
      { id: 2, name: "Snacks", is_system: true, color: "#f59e0b", icon: "cookie" },
    ]),
    getAccounts: vi.fn().mockResolvedValue([
      {
        id: 10,
        name: "Konto domowe",
        type: "checking",
        currency: "PLN",
        initial_balance: "1000.00",
        current_balance: "1000.00",
        is_on_budget: true,
        is_active: true,
      },
    ]),
    verifyTransaction: vi.fn().mockResolvedValue({}),
    rejectInboxItem: vi.fn().mockResolvedValue({}),
    deleteTransaction: vi.fn().mockResolvedValue(undefined),
  },
}));

const sampleTx: TransactionRead = {
  id: 55,
  merchant_name: "Lidl Polska",
  date: "2026-06-15T10:00:00Z",
  total_amount: "25.00",
  currency: "PLN",
  account_id: 10,
  review_status: "pending",
  canonical_total_valid: true,
  review_reasons: [],
  source_records: [
    {
      id: 1,
      budget_id: 1,
      source_type: "MERCHANT_API",
      provider: "lidl",
      external_id: "lidl-55",
      adapter_version: "lidl_plus_v3",
      acquired_at: "2026-06-15T10:05:00Z",
      quality: "1.0000",
      raw_payload_policy: "canonical_only",
    },
  ],
  receipt_scan: {
    id: 3,
    status: "CATEGORIZATION_OK",
    processed_via: "lidl_plus_v3",
    needs_review: false,
    created_at: "2026-06-15T10:05:00Z",
  },
  lines: [
    {
      id: 101,
      name: "Chleb żytni",
      price: "10.00",
      quantity: "1",
      category_id: 1,
      category_source: "cache",
      is_adjustment: false,
    },
    {
      id: 102,
      name: "Baton proteinowy",
      price: "15.00",
      quantity: "1",
      category_id: 2,
      category_source: "ai",
      is_adjustment: false,
    },
  ],
};

describe("VerificationCard provenance & category sources", () => {
  it("shows provenance badges, positive sum check, and cache/ai badges per line", async () => {
    render(<VerificationCard transaction={sampleTx} onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Lidl Plus").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("Dane ustrukturyzowane").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Suma zgodna").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cache").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AI").length).toBeGreaterThan(0);

    // Collapsing all items keeps provenance badges visible in collapsed view too
    const collapseAllButtons = screen.getAllByRole("button", { name: /Zwiń wszystkie/i });
    fireEvent.click(collapseAllButtons[0]);
    expect(screen.getAllByText("Cache").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AI").length).toBeGreaterThan(0);
  });

  it("switches verified total badge to edited mismatch warning when header total changes", async () => {
    render(<VerificationCard transaction={sampleTx} onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Suma zgodna").length).toBeGreaterThan(0);
    });

    const totalInputs = screen.getAllByDisplayValue("25.00");
    fireEvent.change(totalInputs[0], { target: { value: "30.00" } });

    await waitFor(() => {
      expect(screen.getAllByText(/Zmodyfikowano lokalnie/i).length).toBeGreaterThan(0);
    });
  });
});
