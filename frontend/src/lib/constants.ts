export const CATEGORY_LABELS: Record<string, string> = {
  Food: "Jedzenie",
  Housing: "Dom",
  Transport: "Transport",
  Utilities: "Rachunki",
  Entertainment: "Rozrywka",
  Health: "Zdrowie",
  Clothing: "Odzież",
  Kids: "Dzieci",
  Pets: "Zwierzęta",
  Travel: "Podróże",
  Education: "Edukacja",
  Savings: "Oszczędności",
  Gifts: "Prezenty",
  Snacks: "Przekąski",
  Other: "Inne",
  Salary: "Wypłata",
  
  // Synonimy i mapowania AI
  FastFood: "Fast Food",
  "Fast Food": "Fast Food",
  Snack: "Przekąski",
  Vegetables: "Jedzenie",
  Chemicals: "Chemia",
  Electronics: "Elektronika",
};

export const CATEGORY_COLORS: Record<string, string> = {
  Food: "bg-red-100 text-red-700 hover:bg-red-200",
  Housing: "bg-orange-100 text-orange-700 hover:bg-orange-200",
  Transport: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Utilities: "bg-yellow-100 text-yellow-700 hover:bg-yellow-200",
  Entertainment: "bg-purple-100 text-purple-700 hover:bg-purple-200",
  Health: "bg-green-100 text-green-700 hover:bg-green-200",
  Clothing: "bg-pink-100 text-pink-700 hover:bg-pink-200",
  Kids: "bg-sky-100 text-sky-700 hover:bg-sky-200",
  Pets: "bg-violet-100 text-violet-700 hover:bg-violet-200",
  Travel: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  Education: "bg-indigo-100 text-indigo-700 hover:bg-indigo-200",
  Savings: "bg-amber-100 text-amber-700 hover:bg-amber-200",
  Gifts: "bg-rose-100 text-rose-700 hover:bg-rose-200",
  Snacks: "bg-yellow-100 text-yellow-700 hover:bg-yellow-200",
  Other: "bg-gray-100 text-gray-700 hover:bg-gray-200",
  Salary: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200",
  // Fallbacks
  FastFood: "bg-orange-100 text-orange-700 hover:bg-orange-200",
  "Fast Food": "bg-orange-100 text-orange-700 hover:bg-orange-200",
  Snack: "bg-yellow-100 text-yellow-700 hover:bg-yellow-200",
  Vegetables: "bg-red-100 text-red-700 hover:bg-red-200",
  Chemicals: "bg-blue-100 text-blue-700 hover:bg-blue-200",
  Electronics: "bg-pink-100 text-pink-700 hover:bg-pink-200",
};

export const CATEGORY_HEX_COLORS: Record<string, string> = {
  Food: "#f87171",
  Housing: "#fb923c",
  Transport: "#60a5fa",
  Utilities: "#facc15",
  Entertainment: "#c084fc",
  Health: "#4ade80",
  Clothing: "#f472b6",
  Kids: "#38bdf8",
  Pets: "#a78bfa",
  Travel: "#34d399",
  Education: "#818cf8",
  Savings: "#fbbf24",
  Gifts: "#fb7185",
  Snacks: "#fcd34d",
  Other: "#9ca3af",
  Salary: "#10b981",
  // Fallbacks
  FastFood: "#fb923c",
  "Fast Food": "#fb923c",
  Snack: "#fcd34d",
  Vegetables: "#f87171",
  Chemicals: "#60a5fa",
  Electronics: "#f472b6",
};

// Główne kategorie używane w Selectach
export const CATEGORIES = [
  "Food", "Housing", "Transport", "Utilities", "Entertainment", "Health",
  "Clothing", "Kids", "Pets", "Travel", "Education", "Savings", "Gifts",
  "Snacks", "Other", "Salary"
];

export const TAG_COLORS = [
  "#2563eb", // Blue 600
  "#059669", // Emerald 600
  "#dc2626", // Red 600
  "#d97706", // Amber 600
  "#7c3aed", // Purple 600
  "#db2777", // Pink 600
  "#0891b2", // Cyan 600
  "#4f46e5", // Indigo 600
  "#475569", // Slate 600
  "#ca8a04", // Yellow 600 (Darker)
];