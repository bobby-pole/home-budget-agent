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
  date: string;         // Backend zwraca datę jako string ISO
  total_amount: number;
  currency: string;
  image_path?: string;
  status: 'pending' | 'processing' | 'done' | 'error';
  is_manual?: boolean;
  items: Item[];        // To jest ta tablica, którą dodaliśmy przed chwilą w backendzie
}