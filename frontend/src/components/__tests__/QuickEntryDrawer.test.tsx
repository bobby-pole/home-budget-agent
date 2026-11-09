import { render, screen, waitFor } from "../../__tests__/test-utils"
import userEvent from "@testing-library/user-event"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { QuickEntryDrawer } from "../QuickEntryDrawer"
import { api } from "@/lib/api"
import { MemoryRouter } from "react-router-dom"

const mockNavigate = vi.fn()
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom")
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

let mockIsDemo = false
vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    isDemo: mockIsDemo,
    user: { email: mockIsDemo ? "demo@rachownik.app" : "user@example.com" },
  }),
  useOptionalAuth: () => ({
    isDemo: mockIsDemo,
    user: { email: mockIsDemo ? "demo@rachownik.app" : "user@example.com" },
  }),
}))

vi.mock("@/lib/api", () => ({
  api: {
    getDemoQuota: vi.fn(),
    scanSampleReceipt: vi.fn(),
    scanTransaction: vi.fn(),
  },
}))

describe("QuickEntryDrawer", () => {
  const onOpenChange = vi.fn()
  const onManualEntry = vi.fn()
  const onScanReceipt = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockIsDemo = false
    vi.mocked(api.getDemoQuota).mockResolvedValue({
      is_demo: true,
      daily_limit: 5,
      used: 1,
      remaining: 4,
      can_scan: true,
    })
  })

  it("renders standard mode options when not in demo", () => {
    mockIsDemo = false
    render(
      <MemoryRouter>
        <QuickEntryDrawer
          open={true}
          onOpenChange={onOpenChange}
          onManualEntry={onManualEntry}
          onScanReceipt={onScanReceipt}
        />
      </MemoryRouter>
    )

    expect(screen.getByText(/Zrób zdjęcie \/ Wgraj paragon/i)).toBeInTheDocument()
    expect(screen.getByText(/Wpisz ręcznie/i)).toBeInTheDocument()
    expect(screen.queryByText(/Wzorcowe paragony demonstracyjne/i)).not.toBeInTheDocument()
  })

  it("renders sample gallery and quota indicator in demo mode", async () => {
    mockIsDemo = true
    render(
      <MemoryRouter>
        <QuickEntryDrawer
          open={true}
          onOpenChange={onOpenChange}
          onManualEntry={onManualEntry}
          onScanReceipt={onScanReceipt}
        />
      </MemoryRouter>
    )

    expect(await screen.findByText(/Wzorcowe paragony demonstracyjne/i)).toBeInTheDocument()
    expect(screen.getByText(/Biedronka \(Katowice\)/i)).toBeInTheDocument()
    expect(screen.getByText(/Lidl Plus \(Rybnik\)/i)).toBeInTheDocument()

    await waitFor(() => {
      expect(api.getDemoQuota).toHaveBeenCalled()
    })

    expect(await screen.findByText(/Pozostało 4 z 5 prób/i)).toBeInTheDocument()
  })

  it("clicking manual entry triggers onManualEntry callback", async () => {
    const user = userEvent.setup()
    mockIsDemo = false
    render(
      <MemoryRouter>
        <QuickEntryDrawer
          open={true}
          onOpenChange={onOpenChange}
          onManualEntry={onManualEntry}
          onScanReceipt={onScanReceipt}
        />
      </MemoryRouter>
    )

    const manualCard = screen.getByText(/Wpisz ręcznie/i).closest("div[class*='cursor-pointer']")
    expect(manualCard).toBeInTheDocument()
    if (manualCard) {
      await user.click(manualCard)
    }

    expect(onManualEntry).toHaveBeenCalled()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("triggers sample scan and navigates to /inbox in demo mode", async () => {
    const user = userEvent.setup()
    mockIsDemo = true
    vi.mocked(api.scanSampleReceipt).mockResolvedValue({
      id: 201,
      merchant_name: "Biedronka (Wzorzec)",
      total_amount: 101.74,
      currency: "PLN",
      date: "2026-11-09",
      lines: [],
    })

    render(
      <MemoryRouter>
        <QuickEntryDrawer
          open={true}
          onOpenChange={onOpenChange}
          onManualEntry={onManualEntry}
          onScanReceipt={onScanReceipt}
        />
      </MemoryRouter>
    )

    const testButtons = await screen.findAllByRole("button", { name: /przetestuj ten paragon/i })
    expect(testButtons.length).toBe(2)

    await user.click(testButtons[0])

    await waitFor(() => {
      expect(api.scanSampleReceipt).toHaveBeenCalledWith("biedronka")
      expect(onOpenChange).toHaveBeenCalledWith(false)
      expect(mockNavigate).toHaveBeenCalledWith("/inbox")
    })
  })
})
