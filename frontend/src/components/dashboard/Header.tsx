import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Bell, Search, Upload } from "lucide-react";

export function Header() {
  return (
    <header className="flex items-center justify-between px-6 py-4">
      <h1 className="text-2xl font-bold text-foreground">Smart Budget AI</h1>
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="rounded-full">
          <Search className="h-5 w-5 text-muted-foreground" />
          <span className="sr-only">Szukaj</span>
        </Button>
        <Button variant="ghost" size="icon" className="rounded-full">
          <Bell className="h-5 w-5 text-muted-foreground" />
          <span className="sr-only">Powiadomienia</span>
        </Button>
        <Avatar className="h-9 w-9">
          <AvatarImage
            src="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=32&h=32&fit=crop&crop=face"
            alt="User"
          />
          <AvatarFallback>JD</AvatarFallback>
        </Avatar>
        <Button className="rounded-xl bg-primary text-primary-foreground hover:bg-primary/90">
          <Upload className="mr-2 h-4 w-4" />
          Prześlij Paragon
        </Button>
      </div>
    </header>
  );
}
