import { Dashboard } from "./pages/Dashboard";
import { Toaster } from "sonner";
import { ThemeProvider } from "@/lib/ThemeProvider";

function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="budget-ai-theme">
      <div className="min-h-screen bg-background"> 
        <Dashboard />
        <Toaster position="top-right" richColors />
      </div>
    </ThemeProvider>
  )
}

export default App