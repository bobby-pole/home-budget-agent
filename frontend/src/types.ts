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
  owner_id?: number;
}

export interface Item {
  id: number;
  name: string;
  price: number;
  quantity: number;
  category: string | null;
}

export interface Receipt {
  id: number;
  merchant_name: string;
  date: string;
  total_amount: number;
  currency: string;
  image_path?: string;
  status: 'pending' | 'processing' | 'done' | 'error';
  is_manual?: boolean;
  category_id?: number;
  category?: Category;
  tags?: Tag[];
  items: Item[];
}