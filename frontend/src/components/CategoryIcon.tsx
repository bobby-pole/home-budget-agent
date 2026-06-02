import * as Icons from "lucide-react";
import { type LucideProps } from "lucide-react";

// Map legacy emojis to Lucide icon names (PascalCase matching lucide-react exports)
const emojiMap: Record<string, string> = {
  "🍔": "Utensils",
  "🏠": "Home",
  "🚗": "Car",
  "💡": "Lightbulb",
  "🎬": "Clapperboard",
  "⚕️": "HeartPulse",
  "👕": "Shirt",
  "🧸": "ToyBrick",
  "🐕": "PawPrint",
  "✈️": "Plane",
  "📚": "GraduationCap",
  "💰": "Coins",
  "🎁": "Gift",
  "🥨": "Cookie",
  "📦": "Package",
  "🛒": "ShoppingCart",
};

// Map kebab-case (e.g. "heart-pulse") to PascalCase (e.g. "HeartPulse")
const toPascalCase = (str: string): string => {
  return str
    .split("-")
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join("");
};

interface CategoryIconProps extends Omit<LucideProps, "ref"> {
  name: string;
}

export function CategoryIcon({ name, ...props }: CategoryIconProps) {
  if (!name) {
    return <Icons.HelpCircle {...props} />;
  }

  // 1. Try resolving through the emoji map
  let iconName = emojiMap[name];

  if (!iconName) {
    // 2. If it's a regular string, convert from kebab-case/camelCase to PascalCase
    iconName = toPascalCase(name);
  }

  // 3. Grab the component from the lucide-react library exports
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const IconComponent = (Icons as any)[iconName];

  if (!IconComponent) {
    // Fallback icon if none of the above matches or if the icon is not found
    return <Icons.HelpCircle {...props} />;
  }

  return <IconComponent {...props} />;
}
