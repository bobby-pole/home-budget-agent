import type { Receipt, Item, User, AuthResponse } from "@/types";

export function makeUser(overrides?: Partial<User>): User {
  return {
    id: 1,
    email: "test@example.com",
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeItem(overrides?: Partial<Item>): Item {
  return {
    id: 1,
    name: "Mleko",
    price: 3.99,
    quantity: 2,
    category: "Food",
    ...overrides,
  };
}

export function makeReceipt(overrides?: Partial<Receipt>): Receipt {
  return {
    id: 1,
    merchant_name: "Biedronka",
    date: "2024-01-15T10:00:00Z",
    total_amount: 49.99,
    currency: "PLN",
    status: "done",
    is_manual: false,
    items: [makeItem()],
    ...overrides,
  };
}

export function makeAuthResponse(overrides?: Partial<AuthResponse>): AuthResponse {
  return {
    access_token: "mock-jwt-token",
    token_type: "bearer",
    user: makeUser(),
    ...overrides,
  };
}
