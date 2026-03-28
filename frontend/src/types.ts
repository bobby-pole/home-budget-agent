// frontend/src/types.ts

export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Category {
  id: number;
  name: string;
  icon?: string;
  color?: string;
  is_system: boolean;
  parent_id?: number;
  owner_id?: number;
  order_index?: number;
}

export interface Tag {
  id: number;
  name: string;
  color?: string;
  owner_id?: number;
}

export interface TransactionLine {
  id: number;
  name: string;
  price: number;
  quantity: number;
  category_id: number | null;
}

export interface ReceiptScan {
  id: number;
  status: 'processing' | 'done' | 'error' | 'needs_review';
  image_path?: string | null;
  content_hash?: string | null;
  created_at: string;
}

export interface Transaction {
  id: number;
  merchant_name: string;
  date: string;
  total_amount: number;
  currency: string;
  is_manual?: boolean;
  type: 'expense' | 'income' | 'transfer';
  note?: string;
  category_id?: number;
  tags?: Tag[];
  lines: TransactionLine[];
  receipt_scan?: ReceiptScan | null;
}

export interface BudgetCategoryLimit {
  id: number;
  category_id: number;
  amount: number;
}

export interface MonthlyBudget {
  id?: number;
  month: number;
  year: number;
  amount: number;
  user_id: number;
  category_limits: BudgetCategoryLimit[];
}

export interface CategoryBudgetSummaryItem {
  category_id: number;
  category_name: string;
  planned: number;
  spent: number;
  remaining: number;
}

export interface MonthlyBudgetSummary {
  year: number;
  month: number;
  total_planned: number;
  total_spent: number;
  total_remaining: number;
  total_income: number;
  categories: CategoryBudgetSummaryItem[];
}
