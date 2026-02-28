import { render, screen } from "../../__tests__/test-utils"
import { describe, it, expect } from "vitest"
import { BottomNav } from "../BottomNav"
import { MemoryRouter } from "react-router-dom"

describe("BottomNav", () => {
  it("should render mobile navigation items", () => {
    render(
      <MemoryRouter>
        <BottomNav />
      </MemoryRouter>
    );
    
    expect(screen.getByText("Dash")).toBeInTheDocument();
    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.getByText("Trans")).toBeInTheDocument();
    expect(screen.getByText("Inbox")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});
