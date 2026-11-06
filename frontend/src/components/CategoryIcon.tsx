import * as Icons from "lucide-react";
import { type LucideProps } from "lucide-react";

// Map legacy and common emojis to Lucide icon names (PascalCase matching lucide-react exports)
const emojiMap: Record<string, string> = {
  "🍔": "Utensils",
  "🍽️": "UtensilsCrossed",
  "☕": "Coffee",
  "🏠": "Home",
  "🏢": "Building2",
  "🚗": "Car",
  "⛽": "Fuel",
  "⚡": "Zap",
  "💡": "Lightbulb",
  "📶": "Wifi",
  "📱": "Smartphone",
  "🎬": "Clapperboard",
  "📺": "Tv",
  "🎮": "Gamepad2",
  "🎟️": "Ticket",
  "🎉": "PartyPopper",
  "⚕️": "HeartPulse",
  "✨": "Sparkles",
  "👕": "Shirt",
  "🧸": "ToyBrick",
  "🐕": "PawPrint",
  "✈️": "Plane",
  "🏖️": "Palmtree",
  "🌴": "Palmtree",
  "📚": "GraduationCap",
  "💰": "Coins",
  "🐷": "PiggyBank",
  "🛡️": "ShieldCheck",
  "🎁": "Gift",
  "🥨": "Cookie",
  "📦": "Package",
  "🛒": "ShoppingCart",
  "🛍️": "ShoppingBag",
};

// Map kebab-case (e.g. "heart-pulse", "building-2") to PascalCase (e.g. "HeartPulse", "Building2")
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
    // 4. If name is an emoji without direct Lucide mapping, render it as emoji text directly
    if (/\p{Emoji}/u.test(name)) {
      return (
        <span
          className={props.className}
          style={{ fontSize: typeof props.size === "number" ? `${props.size}px` : "1.25rem", lineHeight: 1 }}
        >
          {name}
        </span>
      );
    }
    // Fallback icon
    return <Icons.HelpCircle {...props} />;
  }

  return <IconComponent {...props} />;
}
