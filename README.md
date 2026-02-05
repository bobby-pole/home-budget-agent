# Smart Budget AI 🧾🤖

**Smart Budget AI** is a professional, self-hosted personal finance management application designed with a focus on privacy and automation. By leveraging OpenAI's large language models, the system automatically extracts merchant details, dates, line items, and pricing from uploaded receipt images, converting unstructured visual data into actionable financial insights.

## 🌟 Key Features

- **AI-Powered Parsing:** High-accuracy extraction of receipt data using OpenAI's `gpt-4o-mini` model.
- **Privacy-Centric Architecture:** Images are processed in memory and deleted immediately after successful parsing. All financial records are stored in a local SQLite database.
- **Advanced Dashboard:** High-performance analytics interface featuring *Glassmorphism* design patterns with full support for **Light** and **Dark** modes.
- **Dynamic Budget Management:** Set monthly income targets and track remaining balance in real-time with automated overspending alerts.
- **Granular Data Control:** Full CRUD capabilities for every extracted field, including merchant metadata and individual line items.
- **Historical Analysis:** Comprehensive monthly spending history and interactive bar charts aggregated by category.
- **Integrity Checks:** SHA256 file hashing prevents duplicate data entry.
- **Resource Optimization:** Engineered specifically for low-resource environments (effectively runs on a 1GB RAM VPS).

## 🛠 Technical Stack

### Backend
- **FastAPI** (Python 3.11+) - Asynchronous high-performance API framework.
- **SQLModel** - Pydantic-based ORM for seamless SQLite integration.
- **OpenAI SDK** - Integration for computer vision and data structuring.

### Frontend
- **React 19** + **Vite** + **TypeScript**.
- **Tailwind CSS 4** + **Shadcn/UI** - Modern, responsive component architecture.
- **TanStack Query** - Efficient server-state management and caching.
- **Recharts** - Declarative charting library for financial data visualization.

## 🚀 Getting Started

### Prerequisites
- Docker and Docker Compose.
- OpenAI API Key.

### Environment Configuration
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_api_key_here
ENVIRONMENT=development
```

### Local Development
1. **Start the Backend (Docker):**
   ```bash
   docker-compose up --build -d
   ```
2. **Start the Frontend (Local):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
The application will be accessible at `http://localhost:5173`.

## 📦 Production Deployment (VPS)

This project supports a "Lean Build" workflow to minimize memory usage on servers with limited RAM:

1. Build assets locally: `cd frontend && npm run build`.
2. Transfer the project directory (including `frontend/dist`) to your server.
3. On the server, execute:
   ```bash
   docker-compose -f docker-compose.prod.yml up --build -d
   ```

## 📂 Project Structure
- `/backend` - API logic, database schemas, and AI services.
- `/frontend` - React application source code and assets.
- `/data` - Persistent storage for the SQLite database.
- `Dockerfile.vps` - Optimized production image for low-RAM environments.
