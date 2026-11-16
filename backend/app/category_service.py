"""Centralized category defaults, budget-scoped queries, and seeding helpers."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from .models import Category

DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"name": "Food", "icon": "utensils", "color": "#f87171"},
    {"name": "Housing", "icon": "home", "color": "#fb923c"},
    {"name": "Transport", "icon": "car", "color": "#60a5fa"},
    {"name": "Utilities", "icon": "lightbulb", "color": "#facc15"},
    {"name": "Entertainment", "icon": "clapperboard", "color": "#c084fc"},
    {"name": "Health", "icon": "heart-pulse", "color": "#4ade80"},
    {"name": "Clothing", "icon": "shirt", "color": "#f472b6"},
    {"name": "Kids", "icon": "toy-brick", "color": "#38bdf8"},
    {"name": "Pets", "icon": "paw-print", "color": "#a78bfa"},
    {"name": "Travel", "icon": "plane", "color": "#34d399"},
    {"name": "Education", "icon": "graduation-cap", "color": "#818cf8"},
    {"name": "Savings", "icon": "coins", "color": "#fbbf24"},
    {"name": "Gifts", "icon": "gift", "color": "#fb7185"},
    {"name": "Snacks", "icon": "cookie", "color": "#fcd34d"},
    {"name": "Other", "icon": "package", "color": "#9ca3af"},
]


def seed_default_categories(
    session: Session,
    budget_id: int,
    *,
    commit: bool = True,
) -> list[Category]:
    """Seed the canonical English system categories for a budget."""
    created: list[Category] = []
    for index, cat_data in enumerate(DEFAULT_CATEGORIES):
        category = Category(
            name=cat_data["name"],
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_system=True,
            budget_id=budget_id,
            order_index=index,
        )
        session.add(category)
        created.append(category)
    if commit:
        session.commit()
        for category in created:
            session.refresh(category)
    else:
        session.flush()
    return created


def get_budget_categories(session: Session, budget_id: int) -> list[Category]:
    """Return all categories belonging strictly to the given budget."""
    return list(
        session.exec(
            select(Category).where(Category.budget_id == budget_id)
        ).all()
    )


def get_budget_category_dicts(session: Session, budget_id: int) -> list[dict[str, Any]]:
    """Return budget-scoped categories formatted for AIService prompts."""
    return [
        {"id": cat.id, "name": cat.name}
        for cat in get_budget_categories(session, budget_id)
        if cat.id is not None
    ]
