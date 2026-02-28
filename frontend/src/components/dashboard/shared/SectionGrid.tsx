import { cn } from "@/lib/utils";

interface SectionGridProps {
  children: React.ReactNode;
  className?: string;
}

export function SectionGrid({ children, className }: SectionGridProps) {
  return (
    <div className={cn("grid grid-cols-2 gap-6 p-4 border rounded-lg bg-muted/20", className)}>
      {children}
    </div>
  );
}
