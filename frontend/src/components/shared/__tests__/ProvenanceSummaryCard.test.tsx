import { describe, expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import type { TransactionRead } from "@/client";
import { ProvenanceSummaryCard } from "@/components/shared/ProvenanceSummaryCard";

const structuredLidlTx: TransactionRead = {
  id: 42,
  merchant_name: "Lidl Rybnik",
  total_amount: "99.50",
  currency: "PLN",
  date: "2026-06-10T14:20:00Z",
  is_manual: false,
  type: "expense",
  review_status: "approved",
  canonical_total_valid: true,
  review_reasons: [],
  source_records: [
    {
      id: 7,
      budget_id: 1,
      source_type: "MERCHANT_API",
      provider: "lidl",
      external_id: "lidl-ticket-42",
      adapter_version: "lidl_plus_v3",
      acquired_at: "2026-06-10T14:25:00Z",
      quality: "1.0000",
      raw_payload_policy: "canonical_only",
    },
  ],
  receipt_scan: {
    id: 9,
    status: "DONE",
    processed_via: "lidl_plus_v3",
    needs_review: false,
    created_at: "2026-06-10T14:25:00Z",
  },
};

describe("ProvenanceSummaryCard", () => {
  it("renders structured provenance, deterministic badge, and verified total check without OCR percentage", () => {
    render(<ProvenanceSummaryCard transaction={structuredLidlTx} />);

    expect(screen.getByText("Lidl Plus")).toBeInTheDocument();
    expect(screen.getByText("Dane ustrukturyzowane")).toBeInTheDocument();
    expect(screen.getByText("Suma zgodna")).toBeInTheDocument();
    expect(screen.queryByText(/Jakość OCR/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Szczegóły pochodzenia/i }));
    expect(screen.getByText("lidl_plus_v3")).toBeInTheDocument();
    expect(screen.getByText("lidl-ticket-42")).toBeInTheDocument();
    expect(screen.getByText(/deterministyczna/i)).toBeInTheDocument();
  });

  it("renders OCR quality percentage, failure badge, and actionable review reasons", () => {
    const ocrFailedTx: TransactionRead = {
      ...structuredLidlTx,
      canonical_total_valid: false,
      review_reasons: ["RECEIPT_SUM_MISMATCH:2.00", "MISSING_ACCOUNT"],
      source_records: [
        {
          id: 8,
          budget_id: 1,
          source_type: "OCR_PHOTO",
          provider: "google_vision",
          adapter_version: "ocr_pipeline_v1",
          acquired_at: "2026-06-10T14:25:00Z",
          quality: "0.7800",
          raw_payload_policy: "ephemeral_image",
        },
      ],
      receipt_scan: {
        id: 10,
        status: "NEEDS_REVIEW",
        processed_via: "ocr_pipeline_v1",
        needs_review: true,
        created_at: "2026-06-10T14:25:00Z",
        validation_message: "RECEIPT_SUM_MISMATCH:2.00",
      },
    };

    render(
      <ProvenanceSummaryCard
        transaction={ocrFailedTx}
        liveLinesTotal="97.50"
        liveHeaderTotal="99.50"
      />,
    );

    expect(screen.getByText("Skan OCR")).toBeInTheDocument();
    expect(screen.getByText(/Jakość OCR: 78%/i)).toBeInTheDocument();
    expect(screen.queryByText("Suma zgodna")).not.toBeInTheDocument();
    expect(screen.getByText(/Niezgodność sumy: 2\.00 PLN/i)).toBeInTheDocument();
    expect(screen.getByText(/Suma pozycji różni się od paragonu o 2.00 zł/i)).toBeInTheDocument();
    expect(screen.getByText(/Brak przypisanego konta/i)).toBeInTheDocument();
  });
});
