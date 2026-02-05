import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ThemeToggle } from "./ThemeToggle";

export function Header() {
  return (
    <header className="flex items-center justify-between px-6 py-4">
      <h1 className="text-2xl font-bold text-foreground">Smart Budget AI</h1>
      <div className="flex items-center gap-2 lg:gap-4">
        <ThemeToggle />
        <Avatar className="h-9 w-9 border">
          <AvatarImage
            src="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=32&h=32&fit=crop&crop=face"
            alt="User"
          />
          <AvatarFallback>JD</AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}
