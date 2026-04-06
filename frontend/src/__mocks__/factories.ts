import type { TransactionRead, TransactionLineRead, UserRead, Token } from "@/client";

export function makeUser(overrides?: Partial<UserRead>): UserRead {
  return {
    id: 1,
    email: "test@example.com",
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeTransactionLine(overrides?: Partial<TransactionLineRead>): TransactionLineRead {
  return {
    id: 1,
    name: "Mleko",
    price: 3.99,
    quantity: 2,
    category_id: null,
    ...overrides,
  };
}

export function makeTransaction(overrides?: Partial<TransactionRead>): TransactionRead {
  return {
    id: 1,
    merchant_name: "Biedronka",
    date: "2024-01-15T10:00:00Z",
    total_amount: 49.99,
    currency: "PLN",
    type: "expense",
    is_manual: false,
    lines: [makeTransactionLine()],
    receipt_scan: null,
    ...overrides,
  };
}

export function makeAuthResponse(overrides?: Partial<Token>): Token {
  return {
    access_token: "mock-jwt-token",
    token_type: "bearer",
    user: makeUser(),
    ...overrides,
  };
}
