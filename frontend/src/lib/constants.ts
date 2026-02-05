export const CATEGORY_LABELS: Record<string, string> = {
  Food: "Jedzenie",
  FastFood: "Fast Food",
  Snacks: "Przekąski",
  Transport: "Transport",
  Utilities: "Rachunki",
  Entertainment: "Rozrywka",
  Health: "Zdrowie",
  Other: "Inne",
  
  // Mapowania synonimów i starych danych (dla czytelności w UI)
  "Fast Food": "Fast Food",
  Snack: "Przekąski",
  Snack_legacy: "Przekąski",
  Vegetables: "Jedzenie",
  Vegetable: "Jedzenie",
  Alcohol: "Alkohol",
  Chemicals: "Chemia",
  Electronics: "Elektronika",
  Shopping: "Inne", // Zakupy mapujemy teraz do Inne lub ręcznie do Fast Food
};

export const CATEGORY_COLORS: Record<string, string> = {
  Food: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  FastFood: "bg-orange-100 text-orange-700 hover:bg-orange-200",
  Snacks: "bg-pink-100 text-pink-700 hover:bg-pink-200",
  Transport: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Utilities: "bg-amber-100 text-amber-700 hover:bg-amber-200",
  Entertainment: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Health: "bg-red-100 text-red-700 hover:bg-red-200",
  Other: "bg-gray-100 text-gray-700 hover:bg-gray-200",
  // Fallbacks
  "Fast Food": "bg-orange-100 text-orange-700 hover:bg-orange-200",
  Snack: "bg-pink-100 text-pink-700 hover:bg-pink-200",
  Vegetables: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  Alcohol: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Chemicals: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Electronics: "bg-pink-100 text-pink-700 hover:bg-pink-200",
};

export const CATEGORY_HEX_COLORS: Record<string, string> = {
  Food: "#10B981",
  FastFood: "#F97316", // Orange
  Snacks: "#EC4899",   // Pink
  Transport: "#3B82F6",
  Utilities: "#F59E0B",
  Entertainment: "#8B5CF6",
  Health: "#EF4444",
  Other: "#6B7280",
  // Fallbacks
  "Fast Food": "#F97316",
  Snack: "#EC4899",
  Vegetables: "#10B981",
  Alcohol: "#8B5CF6",
  Chemicals: "#3B82F6",
  Electronics: "#EC4899",
};

// Główne kategorie używane w Selectach
export const CATEGORIES = ["Food", "FastFood", "Snacks", "Transport", "Utilities", "Entertainment", "Health", "Other"];