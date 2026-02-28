import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionGrid } from "@/components/dashboard/shared/SectionGrid";

describe("SectionGrid", () => {
  it("renders children", () => {
    render(
      <SectionGrid>
        <span>Child 1</span>
        <span>Child 2</span>
      </SectionGrid>
    );
    expect(screen.getByText("Child 1")).toBeInTheDocument();
    expect(screen.getByText("Child 2")).toBeInTheDocument();
  });

  it("has grid class", () => {
    const { container } = render(
      <SectionGrid>
        <div>content</div>
      </SectionGrid>
    );
    expect(container.firstChild).toHaveClass("grid");
  });

  it("accepts additional className", () => {
    const { container } = render(
      <SectionGrid className="custom-class">
        <div />
      </SectionGrid>
    );
    expect(container.firstChild).toHaveClass("custom-class");
  });

  describe("snapshots", () => {
    it("matches snapshot — default rendering", () => {
      const { asFragment } = render(
        <SectionGrid>
          <span>Item 1</span>
          <span>Item 2</span>
        </SectionGrid>
      );
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — with custom className", () => {
      const { asFragment } = render(
        <SectionGrid className="extra-class">
          <div>content</div>
        </SectionGrid>
      );
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
