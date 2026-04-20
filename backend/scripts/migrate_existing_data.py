#!/usr/bin/env python3
"""
Skrypt do migracji istniejących danych kategorii systemowych
z globalnych na per-budget oraz ujednolicania nazw (Alcohol -> Snacks).

Uruchom: python scripts/migrate_existing_data.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select, col
from app.database import operations_engine
from app.models import Budget, Category

def migrate_and_cleanup_categories():
    """Przenieś kategorie systemowe do każdego budżetu i napraw nazwy."""
    print("🔧 Rozpoczynam migrację i czyszczenie kategorii...")
    
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

    with Session(operations_engine) as session:
        # 1. Usuń stare kategorie globalne (bez budget_id)
        stmt = select(Category).where(col(Category.budget_id).is_(None))
        global_cats = session.exec(stmt).all()
        if global_cats:
            print("🗑️ Usuwam " + str(len(global_cats)) + " osieroconych kategorii globalnych.")
            for c in global_cats:
                session.delete(c)
            session.commit()

        # 2. Pobierz wszystkie budżety
        budgets = session.exec(select(Budget)).all()
        print("Znaleziono " + str(len(budgets)) + " budżetów do przetworzenia.")
        
        for budget in budgets:
            if budget.id is None:
                continue
            
            print("🔍 Przetwarzam budżet '" + str(budget.name) + "' (" + str(budget.id) + "):")

            # A. Zamień Alcohol na Snacks (jeśli istnieje)
            stmt = select(Category).where(
                Category.budget_id == budget.id,
                Category.name == "Alcohol"
            )
            alcohol_cat = session.exec(stmt).first()
            if alcohol_cat:
                print("  🍿 Zamieniam 'Alcohol' -> 'Snacks'")
                alcohol_cat.name = "Snacks"
                alcohol_cat.icon = "🥨"
                alcohol_cat.color = "#fcd34d"
                session.add(alcohol_cat)
                session.commit()

            # B. Sprawdź i dodaj brakujące kategorie z listy domyślnej
            for i, cat_data in enumerate(default_cats):
                stmt = select(Category).where(
                    Category.budget_id == budget.id,
                    Category.name == cat_data["name"]
                )
                existing = session.exec(stmt).first()
                
                if not existing:
                    print(f"  ➕ Dodaję brakującą kategorię: {cat_data['name']}")
                    new_cat = Category(
                        name=cat_data["name"],
                        icon=cat_data["icon"],
                        color=cat_data["color"],
                        is_system=True,
                        budget_id=budget.id,
                        order_index=i
                    )
                    session.add(new_cat)
            
            session.commit()
    
    print("✅ Migracja i czyszczenie zakończone!")

def main():
    try:
        migrate_and_cleanup_categories()
        print("\n🎉 Dane zostały ujednolicone!")
    except Exception as e:
        print(f"❌ Błąd podczas migracji: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
