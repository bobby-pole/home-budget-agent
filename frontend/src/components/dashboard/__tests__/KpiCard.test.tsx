import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KPICard } from "@/components/dashboard/KpiCard";
import { Wallet, Plus } from "lucide-react";

describe("KPICard", () => {
  const baseProps = {
    title: "Wydatki",
    value: "1 234,56 PLN",
    icon: Wallet,
    iconBgColor: "bg-blue-100",
    iconColor: "text-blue-600",
  };

  it("renders title and value", () => {
    render(<KPICard {...baseProps} />);
    expect(screen.getByText("Wydatki")).toBeInTheDocument();
    expect(screen.getByText("1 234,56 PLN")).toBeInTheDocument();
  });

  it("renders icon (svg)", () => {
    const { container } = render(<KPICard {...baseProps} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("does not render progress bar without showProgress", () => {
    render(<KPICard {...baseProps} />);
    expect(screen.queryByText("Zużycie")).not.toBeInTheDocument();
  });

  it("renders progress bar when showProgress=true", () => {
    render(<KPICard {...baseProps} showProgress progressValue={75} />);
    expect(screen.getByText("Zużycie")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("rounds progressValue to integer", () => {
    render(<KPICard {...baseProps} showProgress progressValue={66.7} />);
    expect(screen.getByText("67%")).toBeInTheDocument();
  });

  it("renders action button when action is provided without showProgress", () => {
    const onClick = vi.fn();
    render(
      <KPICard
        {...baseProps}
        action={{ label: "Dodaj", icon: Plus, onClick }}
      />
    );
    expect(screen.getByRole("button", { name: /Dodaj/i })).toBeInTheDocument();
  });

  it("calls action.onClick when button is clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <KPICard
        {...baseProps}
        action={{ label: "Kliknij", icon: Plus, onClick }}
      />
    );
    await user.click(screen.getByRole("button", { name: /Kliknij/i }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not render action button when showProgress=true", () => {
    const onClick = vi.fn();
    render(
      <KPICard
        {...baseProps}
        showProgress
        progressValue={50}
        action={{ label: "Ukryty", icon: Plus, onClick }}
      />
    );
    expect(screen.queryByRole("button", { name: /Ukryty/i })).not.toBeInTheDocument();
  });

  it("adds highlight styles when highlight=true", () => {
    const { container } = render(<KPICard {...baseProps} highlight />);
    expect(container.firstChild).toHaveClass("ring-2");
  });

  describe("snapshots", () => {
    it("matches snapshot — base card", () => {
      const { asFragment } = render(<KPICard {...baseProps} />);
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — with progress bar (65%)", () => {
      const { asFragment } = render(
        <KPICard {...baseProps} showProgress progressValue={65} />
      );
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — with action button", () => {
      const { asFragment } = render(
        <KPICard {...baseProps} action={{ label: "Add", icon: Plus, onClick: vi.fn() }} />
      );
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — highlighted", () => {
      const { asFragment } = render(<KPICard {...baseProps} highlight />);
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
