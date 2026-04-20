#!/usr/bin/env python3
"""
Skrypt do migracji istniejących danych kategorii systemowych
z globalnych na per-budget.

Uruchom: python scripts/migrate_existing_data.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from app.database import operations_engine
from app.models import Budget, Category

def migrate_system_categories():
    """Przenieś kategorie systemowe do każdego budżetu."""
    print("🔧 Rozpoczynam migrację kategorii systemowych...")
    
    with Session(operations_engine) as session:
        # 1. Pobierz wszystkie budżety
        budgets = session.exec(select(Budget)).all()
        print(f"Znaleziono {len(budgets)} budżetów")
        
        # 2. Dla każdego budżetu sprawdź czy ma swoje kategorie systemowe
        default_cats = [
            {"name": "Food", "icon": "🍔", "color": "#f87171"},
            {"name": "Housing", "icon": "🏠", "color": "#60a5fa"},
            {"name": "Transport", "icon": "🚗", "color": "#facc15"},
            {"name": "Utilities", "icon": "💡", "color": "#facc15"},
            {"name": "Entertainment", "icon": "🎬", "color": "#c084fc"},
            {"name": "Health", "icon": "⚕️", "color": "#4ade80"},
            {"name": "Clothing", "icon": "👕", "color": "#f472b6"},
            {"name": "Kids", "icon": "🧸", "color": "#38bdf8"},
            {"name": "Pets", "icon": "🐕", "color": "#a78bfa"},
            {"name": "Travel", "icon": "✈️", "color": "#34d399"},
            {"name": "Education", "icon": "📚", "color": "#818cf8"},
            {"name": "Savings", "icon": "💰", "color": "#fbbf24"},
            {"name": "Gifts", "icon": "🎁", "color": "#fb7185"},
            {"name": "Snacks", "icon": "🥨", "color": "#fcd34d"},
            {"name": "Other", "icon": "📦", "color": "#9ca3af"},
            {"name": "Salary", "icon": "💵", "color": "#10b981"},
        ]
        
        for budget in budgets:
            if budget.id is None:
                continue
                
            # Sprawdź czy budżet ma już kategorie systemowe
            existing = session.exec(
                select(Category).where(
                    Category.budget_id == budget.id,
                    Category.is_system
                )
            ).first()
            
            if existing:
                print(f"  ✅ Budżet '{budget.name}' ({budget.id}) już ma kategorie systemowe")
                continue
            
            print(f"  📦 Tworzę kategorie systemowe dla budżetu '{budget.name}' ({budget.id})")
            
            # Utwórz kategorie dla tego budżetu
            for i, cat_data in enumerate(default_cats):
                cat = Category(
                    name=cat_data["name"],
                    icon=cat_data["icon"],
                    color=cat_data["color"],
                    is_system=True,
                    budget_id=budget.id,
                    order_index=i
                )
                session.add(cat)
            
            session.commit()
            print(f"  ✅ Utworzono {len(default_cats)} kategorii systemowych")
    
    print("✅ Migracja kategorii systemowych zakończona!")

def main():
    try:
        migrate_system_categories()
        print("\n🎉 Migracja zakończona pomyślnie!")
    except Exception as e:
        print(f"❌ Błąd podczas migracji: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()