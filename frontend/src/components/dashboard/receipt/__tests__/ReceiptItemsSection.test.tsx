import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/__tests__/test-utils";
import { ReceiptItemsSection } from "@/components/dashboard/receipt/ReceiptItemsSection";
import { makeItem } from "@/__mocks__/factories";

// ReceiptItemRow uses useMutation — mock the entire module
vi.mock("@/lib/api", () => ({
  api: {
    updateItem: vi.fn(),
  },
}));

// Mock Radix UI Select for ReceiptItemRow in edit mode
vi.mock("@/components/ui/select", () => ({
  Select: ({ children, onValueChange, value }: { children: React.ReactNode; onValueChange?: (v: string) => void; value?: string }) => (
    <select value={value} onChange={(e) => onValueChange?.(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}));

describe("ReceiptItemsSection", () => {
  it("renders section heading 'Pozycje na paragonie'", () => {
    render(<ReceiptItemsSection items={[]} currency="PLN" />);
    expect(screen.getByText("Pozycje na paragonie")).toBeInTheDocument();
  });

  it("shows count 0 for empty list", () => {
    render(<ReceiptItemsSection items={[]} currency="PLN" />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("shows empty state message when list is empty", () => {
    render(<ReceiptItemsSection items={[]} currency="PLN" />);
    expect(screen.getByText("Brak wykrytych pozycji.")).toBeInTheDocument();
  });

  it("renders receipt items", () => {
    const items = [
      makeItem({ id: 1, name: "Jabłka", price: 4.5, quantity: 1, category: "Food" }),
      makeItem({ id: 2, name: "Woda", price: 2.0, quantity: 3, category: "Other" }),
    ];
    render(<ReceiptItemsSection items={items} currency="PLN" />);

    expect(screen.getByText("Jabłka")).toBeInTheDocument();
    expect(screen.getByText("Woda")).toBeInTheDocument();
  });

  it("shows correct item count", () => {
    const items = [makeItem({ id: 1 }), makeItem({ id: 2 }), makeItem({ id: 3 })];
    render(<ReceiptItemsSection items={items} currency="PLN" />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("does not show empty state message when items exist", () => {
    const items = [makeItem({ id: 1, name: "Ser" })];
    render(<ReceiptItemsSection items={items} currency="PLN" />);
    expect(screen.queryByText("Brak wykrytych pozycji.")).not.toBeInTheDocument();
  });

  it("handles items=undefined (no items from backend)", () => {
    render(<ReceiptItemsSection items={undefined as unknown as import("@/types").Item[]} currency="PLN" />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Brak wykrytych pozycji.")).toBeInTheDocument();
  });

  describe("snapshots", () => {
    it("matches snapshot — empty list", () => {
      const { asFragment } = render(<ReceiptItemsSection items={[]} currency="PLN" />);
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — with two items", () => {
      const items = [
        makeItem({ id: 1, name: "Jabłka", price: 4.5, quantity: 1, category: "Food" }),
        makeItem({ id: 2, name: "Woda", price: 2.0, quantity: 3, category: "Other" }),
      ];
      const { asFragment } = render(<ReceiptItemsSection items={items} currency="PLN" />);
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
