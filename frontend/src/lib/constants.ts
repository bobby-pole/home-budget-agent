export const CATEGORY_LABELS: Record<string, string> = {
  Food: "Jedzenie",
  Transport: "Transport",
  Utilities: "Rachunki",
  Shopping: "Zakupy",
  Entertainment: "Rozrywka",
  Health: "Zdrowie",
  Other: "Inne",
  // Legacy mappings (for existing data)
  Alcohol: "Alkohol",
  Chemicals: "Chemia",
  Electronics: "Elektronika",
};

export const CATEGORY_COLORS: Record<string, string> = {
  Food: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  Transport: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Utilities: "bg-amber-100 text-amber-700 hover:bg-amber-200",
  Shopping: "bg-pink-100 text-pink-700 hover:bg-pink-200",
  Entertainment: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Health: "bg-red-100 text-red-700 hover:bg-red-200",
  Other: "bg-gray-100 text-gray-700 hover:bg-gray-200",
  // Legacy mappings
  Alcohol: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Chemicals: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Electronics: "bg-pink-100 text-pink-700 hover:bg-pink-200",
};

export const CATEGORY_HEX_COLORS: Record<string, string> = {
  Food: "#10B981",
  Transport: "#3B82F6",
  Utilities: "#F59E0B",
  Shopping: "#EC4899",
  Entertainment: "#8B5CF6",
  Health: "#EF4444",
  Other: "#6B7280",
  // Legacy mappings
  Alcohol: "#8B5CF6",
  Chemicals: "#3B82F6",
  Electronics: "#EC4899",
};

export const CATEGORIES = Object.keys(CATEGORY_LABELS);
