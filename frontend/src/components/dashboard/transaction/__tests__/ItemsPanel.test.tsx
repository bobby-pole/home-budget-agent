import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ItemsPanel } from "@/components/dashboard/transaction/ItemsPanel";
import type { ManualItem } from "@/components/dashboard/transaction/ItemsPanel";

vi.mock("@/lib/api", () => ({
  api: {
    getCategories: vi.fn().mockResolvedValue([]),
  },
}));

// Mock Radix UI Select — SelectTrigger/SelectValue must return null
// to avoid invalid HTML (<span> inside <select>) in jsdom
vi.mock("@/components/ui/select", () => ({
  Select: ({ children, onValueChange, value }: { children: React.ReactNode; onValueChange?: (v: string) => void; value?: string }) => (
    <select
      data-testid="category-select"
      value={value}
      onChange={(e) => onValueChange?.(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}));

// Stateful wrapper — simulates a controlled parent component
function ItemsPanelWrapper({
  initialItems = [],
  onItemsChange,
}: {
  initialItems?: ManualItem[];
  onItemsChange?: (items: ManualItem[]) => void;
}) {
  const [items, setItems] = useState<ManualItem[]>(initialItems);

  function handleChange(updated: ManualItem[]) {
    setItems(updated);
    onItemsChange?.(updated);
  }

  return <ItemsPanel items={items} currency="PLN" onItemsChange={handleChange} />;
}

describe("ItemsPanel", () => {
  describe("empty state", () => {
    it("shows empty state message", () => {
      render(<ItemsPanelWrapper />);
      expect(
        screen.getByText(/Brak pozycji/i)
      ).toBeInTheDocument();
    });

    it("shows 'Add item' button", () => {
      render(<ItemsPanelWrapper />);
      expect(
        screen.getByRole("button", { name: /Dodaj pozycję/i })
      ).toBeInTheDocument();
    });

    it("does not show item count when list is empty", () => {
      render(<ItemsPanelWrapper />);
      // count badge only renders when items.length > 0
      expect(screen.queryByText("0")).not.toBeInTheDocument();
    });
  });

  describe("draft — adding a new item", () => {
    it("clicking 'Add item' shows draft input fields", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper />);

      await user.click(screen.getByRole("button", { name: /Dodaj pozycję/i }));

      expect(screen.getByPlaceholderText("Nazwa pozycji")).toBeInTheDocument();
      expect(screen.getByPlaceholderText("Cena")).toBeInTheDocument();
    });

    it("'Add item' button is hidden when draft is active", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper />);

      await user.click(screen.getByRole("button", { name: /Dodaj pozycję/i }));

      expect(
        screen.queryByRole("button", { name: /Dodaj pozycję/i })
      ).not.toBeInTheDocument();
    });

    it("Cancel hides draft and restores the button", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper />);

      await user.click(screen.getByRole("button", { name: /Dodaj pozycję/i }));
      // click the last button (X = Cancel)
      const buttons = screen.getAllByRole("button");
      const cancelBtn = buttons[buttons.length - 1];
      await user.click(cancelBtn);

      expect(
        screen.getByRole("button", { name: /Dodaj pozycję/i })
      ).toBeInTheDocument();
    });

    it("filling in draft and confirming adds item to the list", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper />);

      await user.click(screen.getByRole("button", { name: /Dodaj pozycję/i }));

      // fireEvent.change instead of userEvent.type — avoids issues with type="number"
      // inputs and jsdom's character-by-character decimal accumulation
      fireEvent.change(screen.getByPlaceholderText("Nazwa pozycji"), {
        target: { value: "Chleb" },
      });
      fireEvent.change(screen.getByPlaceholderText("Cena"), {
        target: { value: "3.50" },
      });

      // click Confirm button (Check — first button in draft row)
      const confirmBtn = screen.getAllByRole("button")[0];
      await user.click(confirmBtn);

      expect(screen.getByText("Chleb")).toBeInTheDocument();
      expect(screen.getByText("3.50 PLN")).toBeInTheDocument();
    });
  });

  describe("items list", () => {
    const existingItem: ManualItem = {
      id: "item-1",
      name: "Mleko",
      price: 3.99,
      quantity: 1,
      category_id: null,
    };

    it("renders items passed via props", () => {
      render(<ItemsPanelWrapper initialItems={[existingItem]} />);
      expect(screen.getByText("Mleko")).toBeInTheDocument();
    });

    it("shows item count when there are ≥1 items", () => {
      render(<ItemsPanelWrapper initialItems={[existingItem]} />);
      expect(screen.getByText("1")).toBeInTheDocument();
    });

    it("removing an item removes it from the list", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper initialItems={[existingItem]} />);

      const removeBtn = screen.getByRole("button", { name: "" }); // icon-only Trash2 button
      await user.click(removeBtn);

      expect(screen.queryByText("Mleko")).not.toBeInTheDocument();
    });

    it("after removing the last item shows empty state message", async () => {
      const user = userEvent.setup();
      render(<ItemsPanelWrapper initialItems={[existingItem]} />);

      await user.click(screen.getByRole("button", { name: "" }));

      expect(screen.getByText(/Brak pozycji/i)).toBeInTheDocument();
    });

    it("calls onItemsChange after removing an item", async () => {
      const user = userEvent.setup();
      const onItemsChange = vi.fn();
      render(
        <ItemsPanelWrapper
          initialItems={[existingItem]}
          onItemsChange={onItemsChange}
        />
      );

      await user.click(screen.getByRole("button", { name: "" }));

      expect(onItemsChange).toHaveBeenCalledWith([]);
    });

    it("renders multiple items", () => {
      const items: ManualItem[] = [
        { id: "1", name: "Chleb", price: 3.0, quantity: 1, category_id: null },
        { id: "2", name: "Masło", price: 6.5, quantity: 2, category_id: null },
      ];
      render(<ItemsPanelWrapper initialItems={items} />);
      expect(screen.getByText("Chleb")).toBeInTheDocument();
      expect(screen.getByText("Masło")).toBeInTheDocument();
      expect(screen.getByText("2")).toBeInTheDocument(); // count badge
    });

    it("amounts are displayed with currency", () => {
      render(
        <ItemsPanelWrapper
          initialItems={[{ id: "x", name: "Test", price: 10, quantity: 3, category_id: null }]}
        />
      );
      expect(screen.getByText("30.00 PLN")).toBeInTheDocument();
    });
  });

  describe("snapshots", () => {
    it("matches snapshot — empty state", () => {
      const { asFragment } = render(<ItemsPanelWrapper />);
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — with two items", () => {
      const items: ManualItem[] = [
        { id: "1", name: "Chleb", price: 3.0, quantity: 1, category_id: null },
        { id: "2", name: "Masło", price: 6.5, quantity: 2, category_id: null },
      ];
      const { asFragment } = render(<ItemsPanelWrapper initialItems={items} />);
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
