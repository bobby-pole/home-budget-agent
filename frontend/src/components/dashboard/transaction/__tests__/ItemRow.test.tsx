import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import userEvent from "@testing-library/user-event";
import { ItemRow } from "@/components/dashboard/transaction/ItemRow";
import type { ManualItem } from "@/components/dashboard/transaction/ItemRow";

vi.mock("@/lib/api", () => ({
  api: {
    getCategories: vi.fn().mockResolvedValue([
      { id: 1, name: "food", is_system: true, color: "#4caf50", icon: "🍔" },
    ]),
  },
}));

const item: ManualItem = {
  id: "abc-123",
  name: "Mleko UHT",
  price: 3.5,
  quantity: 2,
  category_id: 1,
};

describe("ItemRow", () => {
  it("renders item name", () => {
    render(<ItemRow item={item} currency="PLN" onRemove={vi.fn()} />);
    expect(screen.getByText("Mleko UHT")).toBeInTheDocument();
  });

  it("renders quantity in units", () => {
    render(<ItemRow item={item} currency="PLN" onRemove={vi.fn()} />);
    expect(screen.getByText("2 szt.")).toBeInTheDocument();
  });

  it("renders computed amount (price × quantity)", () => {
    render(<ItemRow item={item} currency="PLN" onRemove={vi.fn()} />);
    // 3.5 * 2 = 7.00
    expect(screen.getByText("7.00 PLN")).toBeInTheDocument();
  });

  it("renders currency from props", () => {
    render(<ItemRow item={{ ...item, price: 10, quantity: 1 }} currency="EUR" onRemove={vi.fn()} />);
    expect(screen.getByText("10.00 EUR")).toBeInTheDocument();
  });

  it("calls onRemove with item id on remove button click", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(<ItemRow item={item} currency="PLN" onRemove={onRemove} />);

    const removeBtn = screen.getByRole("button");
    await user.click(removeBtn);

    expect(onRemove).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledWith("abc-123");
  });

  it("uses item name as title attribute for truncation", () => {
    render(<ItemRow item={item} currency="PLN" onRemove={vi.fn()} />);
    expect(screen.getByTitle("Mleko UHT")).toBeInTheDocument();
  });

  it("does not show category badge when category_id is null", () => {
    render(
      <ItemRow
        item={{ ...item, category_id: null }}
        currency="PLN"
        onRemove={vi.fn()}
      />
    );
    // No category badge should be rendered
    expect(screen.queryByRole("button")).toBeInTheDocument(); // remove button still there
  });

  describe("snapshots", () => {
    it("matches snapshot", () => {
      const { asFragment } = render(
        <ItemRow item={item} currency="PLN" onRemove={vi.fn()} />
      );
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — EUR currency", () => {
      const { asFragment } = render(
        <ItemRow item={{ ...item, price: 10, quantity: 1 }} currency="EUR" onRemove={vi.fn()} />
      );
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
