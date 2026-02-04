import { Dashboard } from "./pages/Dashboard";
import { Toaster } from "sonner";

function App() {
  return (
    <div className="min-h-screen bg-gray-50"> 
      <Dashboard />
      <Toaster position="top-right" richColors />
    </div>
  )
}

export default App