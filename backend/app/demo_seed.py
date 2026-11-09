# backend/app/demo_seed.py
"""
Deterministic Demo Environment Seed Service.

Provides a rich, realistic showcase dataset for public demo mode:
- Demo User & Household Budget
- Bank & Cash Accounts with realistic balances
- Envelope Categories & Monthly Allocations per month
- Realistic monthly income (7 000 PLN) and structured expenses (6 500 PLN), leaving 500 PLN buffer
- Category allocations: Rata 2000, Czynsz 1000, Rachunki 400, Jedzenie 2000, etc.
- Detailed receipt line items for store transactions matching exact totals down to 0.00 PLN
- Automatic monthly auto-seed: updates with fresh income & expenses per month
- Staged / Inbox Receipts (Biedronka, Lidl) with parsed line items awaiting review
"""

import argparse
import calendar
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, col, delete, select

from .auth import hash_password
from .config import settings
from .models import (
    Account,
    Budget,
    BudgetMember,
    Category,
    EnvelopeAllocation,
    ReceiptScan,
    ScanStatus,
    Transaction,
    TransactionLine,
    TransactionStatus,
    User,
)

logger = logging.getLogger(__name__)

DEMO_USER_PASSWORD = "demo_password_123"
DEMO_BUDGET_NAME = "Budżet Domowy (Demo)"

# ─── Category Definitions ───────────────────────────────────────────────────
# (Group name, icon, color, [(Subcat name, icon, color, planned_amount)])
# Planned amounts: 2000 + 1000 + 400 + 2000 + 450 + 250 + 250 + 150 = 6 500.00 PLN
# Monthly Income = 7 000.00 PLN -> Leaves 500.00 PLN ready to assign / buffer.
CATEGORIES_DEF: List[Tuple[str, str, str, List[Tuple[str, str, str, float]]]] = [
    (
        "Stałe opłaty", "building-2", "#f97316", [
            ("Rata za mieszkanie", "home", "#ea580c", 2000.00),
            ("Czynsz administracyjny", "building-2", "#f97316", 1000.00),
            ("Rachunki i Media", "zap", "#eab308", 400.00),
        ]
    ),
    (
        "Codzienne wydatki", "shopping-bag", "#ef4444", [
            ("Żywność i Supermarket", "shopping-cart", "#10b981", 2000.00),
            ("Transport i Paliwo", "fuel", "#06b6d4", 450.00),
            ("Drogeria i Zdrowie", "sparkles", "#ec4899", 250.00),
            ("Restauracje i Kawiarnie", "coffee", "#a855f7", 250.00),
        ]
    ),
    (
        "Rozrywka i Czas wolny", "gamepad-2", "#8b5cf6", [
            ("Rozrywka i Subskrypcje", "tv", "#6366f1", 150.00),
        ]
    ),
    (
        "Oszczędności", "piggy-bank", "#f59e0b", [
            ("Fundusz Awaryjny", "shield-check", "#10b981", 0.00),
        ]
    ),
]

# ─── Transaction Templates ──────────────────────────────────────────────────
# 25 transactions per month:
# 1 Income (7 000 PLN) + 4 Fixed bills (3 400 PLN) + 20 Daily expenses (3 100 PLN)
# Total expenses: 6 500.00 PLN. Net cash flow: +500.00 PLN.
TRANSACTIONS_TEMPLATE = [
    # 1. Income (Day 1)
    (
        "Wynagrodzenie (Pracodawca)", 7000.00, "checking", "income", TransactionStatus.CLEARED, None, "Wypłata za bieżący miesiąc",
        [
            ("Wynagrodzenie zasadnicze", 7000.00, 1.0, None),
        ],
    ),
    # 2. Fixed Bills (Days 2 - 4)
    (
        "Bank Millennium", 2000.00, "checking", "expense", TransactionStatus.CLEARED, "Rata za mieszkanie", "Spłata raty kredytu hipotecznego",
        [
            ("Rata kapitałowo-odsetkowa kredytu", 2000.00, 1.0, "Rata za mieszkanie"),
        ],
    ),
    (
        "Spółdzielnia Mieszkaniowa", 1000.00, "checking", "expense", TransactionStatus.CLEARED, "Czynsz administracyjny", "Czynsz administracyjny za lokal",
        [
            ("Zaliczka na koszty eksploatacji", 550.00, 1.0, "Czynsz administracyjny"),
            ("Fundusz remontowy", 200.00, 1.0, "Czynsz administracyjny"),
            ("Centralne ogrzewanie (zaliczka)", 150.00, 1.0, "Czynsz administracyjny"),
            ("Zimna woda i odprowadzanie ścieków", 100.00, 1.0, "Czynsz administracyjny"),
        ],
    ),
    (
        "PGE Polska Grupa Energetyczna", 260.00, "checking", "expense", TransactionStatus.CLEARED, "Rachunki i Media", "Faktura za energię elektryczną",
        [
            ("Energia elektryczna czynna", 170.00, 1.0, "Rachunki i Media"),
            ("Opłata dystrybucyjna i przesyłowa", 90.00, 1.0, "Rachunki i Media"),
        ],
    ),
    (
        "Orange Polska", 140.00, "checking", "expense", TransactionStatus.CLEARED, "Rachunki i Media", "Światłowód i abonament komórkowy",
        [
            ("Światłowód domowy 600 Mb/s", 90.00, 1.0, "Rachunki i Media"),
            ("Abonament komórkowy 5G", 50.00, 1.0, "Rachunki i Media"),
        ],
    ),
    # 3. Daily Expenses (20 transactions: Groceries, Fuel, Drugstore, Cafes, Subscriptions)
    (
        "Biedronka", 480.00, "checking", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Zakupy tygodniowe",
        [
            ("Pierś z kurczaka filet 1kg", 24.99, 2.0, "Żywność i Supermarket"),
            ("Mielone z szynki 500g", 12.99, 2.0, "Żywność i Supermarket"),
            ("Łosoś atlantycki filet 300g", 29.99, 2.0, "Żywność i Supermarket"),
            ("Mleko Świeże 3.2% 1L", 3.49, 4.0, "Żywność i Supermarket"),
            ("Masło Ekstra 82% 200g", 6.99, 3.0, "Żywność i Supermarket"),
            ("Jaja Chów Ściółkowy M 20szt", 17.99, 1.0, "Żywność i Supermarket"),
            ("Kawa Ziarnista Lavazza Oro 1kg", 69.99, 1.0, "Żywność i Supermarket"),
            ("Oliwa z oliwek Extra Virgin 750ml", 39.99, 1.0, "Żywność i Supermarket"),
            ("Ser Grana Padano 200g", 19.99, 2.0, "Żywność i Supermarket"),
            ("Pomidory Malinowe 1.5kg", 22.39, 1.0, "Żywność i Supermarket"),
            ("Papryka Czerwona 1kg", 14.99, 1.0, "Żywność i Supermarket"),
            ("Ogórek Szklarniowy 1kg", 9.99, 1.0, "Żywność i Supermarket"),
            ("Banan Bio luz 1.5kg", 12.45, 1.0, "Żywność i Supermarket"),
            ("Cytryna Luz 0.5kg", 5.25, 1.0, "Żywność i Supermarket"),
            ("Makaron Barilla Spaghetti 500g", 6.99, 3.0, "Żywność i Supermarket"),
            ("Ryż Basmati 1kg", 8.99, 2.0, "Żywność i Supermarket"),
            ("Płatki Owsiane Górskie 500g", 3.49, 2.0, "Żywność i Supermarket"),
            ("Orzechy Włoskie Łuskane 200g", 15.09, 2.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Lidl", 450.00, "checking", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Zakupy spożywcze",
        [
            ("Polski Kurczak - filet z piersi 1kg", 23.99, 2.0, "Żywność i Supermarket"),
            ("Szynka szwarcwaldzka 100g", 5.99, 3.0, "Żywność i Supermarket"),
            ("Szynka Wieprzowa z Chrzanem 150g", 6.99, 2.0, "Żywność i Supermarket"),
            ("Ser Gouda w plastrach 400g", 11.99, 2.0, "Żywność i Supermarket"),
            ("Mozzarella Galbani 125g", 4.49, 4.0, "Żywność i Supermarket"),
            ("Jogurt Naturalny Pilos 400g", 2.29, 6.0, "Żywność i Supermarket"),
            ("Chleb żytni na zakwasie 500g", 4.49, 3.0, "Żywność i Supermarket"),
            ("Sos pomidorowy Mutti 700g", 8.49, 4.0, "Żywność i Supermarket"),
            ("Krewetki White Tiger 400g", 34.99, 2.0, "Żywność i Supermarket"),
            ("Awokado Hass 2szt", 9.99, 2.0, "Żywność i Supermarket"),
            ("Borówka Amerykańska 500g", 22.99, 2.0, "Żywność i Supermarket"),
            ("Jabłka Polskie Szampion 2kg", 7.98, 2.0, "Żywność i Supermarket"),
            ("Ziemniaki Jadalne 2.5kg", 7.49, 2.0, "Żywność i Supermarket"),
            ("Herbata Zielona Lipton 50 torebek", 12.99, 2.0, "Żywność i Supermarket"),
            ("Woda mineralna Saguaro 1.5L zgrzewka", 11.00, 3.0, "Żywność i Supermarket"),
            ("Czekolada Gorzka 85% Fin Carré 100g", 4.99, 3.0, "Żywność i Supermarket"),
            ("Miód Lipowy Polski 400g", 26.13, 1.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Biedronka", 368.34, "checking", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Uzupełnienie zapasów domowych",
        [
            ("Polędwiczki z piersi kurczaka 400g", 14.99, 2.0, "Żywność i Supermarket"),
            ("Stek z rostbefu wołowego 250g", 26.99, 1.0, "Żywność i Supermarket"),
            ("Krewetki mrożone 450g", 36.99, 1.0, "Żywność i Supermarket"),
            ("Twaróg półtłusty 250g", 4.49, 2.0, "Żywność i Supermarket"),
            ("Jogurt grecki 400g", 4.29, 2.0, "Żywność i Supermarket"),
            ("Ser Camembert President 120g", 6.99, 2.0, "Żywność i Supermarket"),
            ("Pomidorki koktajlowe 500g", 11.99, 2.0, "Żywność i Supermarket"),
            ("Sałata rzymska 2szt", 7.99, 1.0, "Żywność i Supermarket"),
            ("Winogrona jasne bezpestkowe 500g", 12.99, 2.0, "Żywność i Supermarket"),
            ("Czosnek polski 3szt", 5.99, 1.0, "Żywność i Supermarket"),
            ("Kasza jaglana 1kg", 6.49, 2.0, "Żywność i Supermarket"),
            ("Oliwa z pestek winogron 750ml", 29.99, 1.0, "Żywność i Supermarket"),
            ("Musli owocowe 500g", 10.99, 2.0, "Żywność i Supermarket"),
            ("Kawa rozpuszczalna Jacobs 200g", 32.99, 1.0, "Żywność i Supermarket"),
            ("Herbata czarna Earl Grey 100szt", 18.99, 1.0, "Żywność i Supermarket"),
            ("Sok pomarańczowy 100% 1L", 6.99, 4.0, "Żywność i Supermarket"),
            ("Cukier trzcinowy 1kg", 8.99, 1.0, "Żywność i Supermarket"),
            ("Pistacje prażone solone 250g", 25.02, 1.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Lidl", 420.00, "checking", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Zakupy spożywcze i świeże warzywa",
        [
            ("Schab wieprzowy bez kości 1kg", 19.99, 2.0, "Żywność i Supermarket"),
            ("Kiełbasa krakowska sucha 300g", 14.99, 2.0, "Żywność i Supermarket"),
            ("Ser Cheddar dojrzały 250g", 13.99, 2.0, "Żywność i Supermarket"),
            ("Masło orzechowe 100% 470g", 16.99, 2.0, "Żywność i Supermarket"),
            ("Chleb słonecznikowy 500g", 4.89, 3.0, "Żywność i Supermarket"),
            ("Jajka z wolnego wybiegu L 10szt", 12.99, 2.0, "Żywność i Supermarket"),
            ("Oliwa z oliwek Kalamata 500ml", 34.99, 1.0, "Żywność i Supermarket"),
            ("Passata pomidorowa bio 500g", 5.99, 4.0, "Żywność i Supermarket"),
            ("Ryż do risotto Carnaroli 1kg", 14.99, 2.0, "Żywność i Supermarket"),
            ("Cytryny bio 500g", 6.99, 2.0, "Żywność i Supermarket"),
            ("Gruszki Konferencja 1kg", 8.99, 2.0, "Żywność i Supermarket"),
            ("Warzywa na patelnię z przyprawami 450g", 6.49, 4.0, "Żywność i Supermarket"),
            ("Woda gazowana Cisowianka 1.5L zgrzewka", 13.50, 3.0, "Żywność i Supermarket"),
            ("Migdały kalifornijskie 200g", 14.99, 2.0, "Żywność i Supermarket"),
            ("Orzechy nerkowca 200g", 14.32, 1.0, "Żywność i Supermarket"),
            ("Zioła w doniczce bazylia i kolendra", 6.99, 2.0, "Żywność i Supermarket"),
            ("Świeże drożdże piekarskie 100g", 1.80, 1.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Piekarnia Rzemieślnicza", 58.50, "cash", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Świeże pieczywo na zakwasie",
        [
            ("Chleb żytni na zakwasie 800g", 14.50, 2.0, "Żywność i Supermarket"),
            ("Bagietka francuska tradycyjna", 6.50, 2.0, "Żywność i Supermarket"),
            ("Drożdżówka z malinami i kruszonką", 5.50, 3.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Żabka", 41.50, "cash", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Przekąski i napoje",
        [
            ("Hot Dog Gigant sos tysiąca wysp", 8.50, 2.0, "Żywność i Supermarket"),
            ("Pepsi Max 0.5L", 5.50, 2.0, "Żywność i Supermarket"),
            ("Baton proteinowy karmelowy", 8.90, 1.0, "Żywność i Supermarket"),
            ("Orzeszki ziemne solone 100g", 4.60, 1.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Żabka", 70.00, "cash", "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Drugie śniadanie i kawa na mieście",
        [
            ("Kanapka trójkąt z kurczakiem", 8.50, 4.0, "Żywność i Supermarket"),
            ("Smoothie owocowe 300ml", 7.50, 4.0, "Żywność i Supermarket"),
            ("Kawa Americano duża 400ml", 6.00, 1.0, "Żywność i Supermarket"),
        ],
    ),
    (
        "Orlen", 245.00, "checking", "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Tankowanie Pb95 i postój",
        [
            ("Benzyna Pb95 Efecta", 6.49, 35.0, "Transport i Paliwo"),
            ("Kawa Duża Cafe Punkt 400ml", 12.90, 1.0, "Transport i Paliwo"),
            ("Hot Dog Max z Kabanosem", 4.95, 1.0, "Transport i Paliwo"),
        ],
    ),
    (
        "Stacja Shell", 170.50, "checking", "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Paliwo V-Power i płyn do spryskiwaczy",
        [
            ("Paliwo Shell V-Power 95", 6.80, 23.6, "Transport i Paliwo"),
            ("Płyn do spryskiwaczy letni 4L", 10.02, 1.0, "Transport i Paliwo"),
        ],
    ),
    (
        "Uber", 34.50, "checking", "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Przejazd miejski",
        [
            ("Przejazd UberX: Centrum - Mokotów", 34.50, 1.0, "Transport i Paliwo"),
        ],
    ),
    (
        "Rossmann", 78.40, "checking", "expense", TransactionStatus.CLEARED, "Drogeria i Zdrowie", "Kosmetyki i środki czystości",
        [
            ("Żel pod prysznic Dove 400ml", 16.99, 1.0, "Drogeria i Zdrowie"),
            ("Pasta do zębów Elmex Sensitive 75ml", 18.49, 1.0, "Drogeria i Zdrowie"),
            ("Tabletki do zmywarki Somat All-in-One 36szt", 34.99, 1.0, "Drogeria i Zdrowie"),
            ("Mydło w płynie Isana zapas 500ml", 7.93, 1.0, "Drogeria i Zdrowie"),
        ],
    ),
    (
        "Apteka Gemini", 64.30, "checking", "expense", TransactionStatus.CLEARED, "Drogeria i Zdrowie", "Witaminy i apteczka domowa",
        [
            ("Witamina D3 4000 IU 120 kapsułek", 32.50, 1.0, "Drogeria i Zdrowie"),
            ("Magnez B6 Ultra 60 tabletek", 19.80, 1.0, "Drogeria i Zdrowie"),
            ("Plastry Viscoplast z opatrunkiem zestaw", 12.00, 1.0, "Drogeria i Zdrowie"),
        ],
    ),
    (
        "Allegro", 92.16, "checking", "expense", TransactionStatus.CLEARED, "Drogeria i Zdrowie", "Wkłady filtrujące i kosmetyki",
        [
            ("Wkłady filtrujące Dafi Unimax 5+1 szt.", 69.00, 1.0, "Drogeria i Zdrowie"),
            ("Szampon wzmacniający do włosów 400ml", 16.40, 1.0, "Drogeria i Zdrowie"),
            ("Mydło w kostce Dove 100g", 6.76, 1.0, "Drogeria i Zdrowie"),
        ],
    ),
    (
        "Restauracja Manekin", 124.00, "checking", "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Obiad dla dwojga",
        [
            ("Naleśnik z kurczakiem i szpinakiem w sosie gorgonzola", 34.00, 1.0, "Restauracje i Kawiarnie"),
            ("Naleśnik z łososiem wędzonym i ricottą", 38.00, 1.0, "Restauracje i Kawiarnie"),
            ("Lemoniada cytrynowo-miętowa 0.5L", 14.00, 2.0, "Restauracje i Kawiarnie"),
            ("Naleśnik na słodko z mascarpone i owocami", 24.00, 1.0, "Restauracje i Kawiarnie"),
        ],
    ),
    (
        "Green Caffe Nero", 42.00, "checking", "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Kawa i sernik",
        [
            ("Flat White duży (mleko owsiane)", 21.00, 1.0, "Restauracje i Kawiarnie"),
            ("Sernik nowojorski z owocami leśnymi", 21.00, 1.0, "Restauracje i Kawiarnie"),
        ],
    ),
    (
        "Green Caffe Nero", 42.00, "checking", "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Kawa i szarlotka",
        [
            ("Caffe Latte duże", 20.00, 1.0, "Restauracje i Kawiarnie"),
            ("Szarlotka na ciepło z lodami", 22.00, 1.0, "Restauracje i Kawiarnie"),
        ],
    ),
    (
        "Pizzeria / Lunch", 42.00, "checking", "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Lunch w ciągu dnia",
        [
            ("Pizza Margherita 32cm", 32.00, 1.0, "Restauracje i Kawiarnie"),
            ("Napój San Pellegrino 330ml", 10.00, 1.0, "Restauracje i Kawiarnie"),
        ],
    ),
    (
        "Netflix", 43.00, "checking", "expense", TransactionStatus.CLEARED, "Rozrywka i Subskrypcje", "Abonament Standard",
        [
            ("Subskrypcja Plan Standard (HD, 2 ekrany)", 43.00, 1.0, "Rozrywka i Subskrypcje"),
        ],
    ),
    (
        "Spotify", 24.99, "checking", "expense", TransactionStatus.CLEARED, "Rozrywka i Subskrypcje", "Pakiet Duo",
        [
            ("Subskrypcja Spotify Premium Duo", 24.99, 1.0, "Rozrywka i Subskrypcje"),
        ],
    ),
    (
        "Multikino", 82.01, "checking", "expense", TransactionStatus.CLEARED, "Rozrywka i Subskrypcje", "Bilety do kina i popcorn",
        [
            ("Bilet na seans 2D (normalny)", 26.00, 2.0, "Rozrywka i Subskrypcje"),
            ("Zestaw Popcorn duży + 2 napoje", 30.01, 1.0, "Rozrywka i Subskrypcje"),
        ],
    ),
]


B2_FULL_ITEMS = [
    ("Polędwiczki z piersi kurczaka 400g", 14.99, 3.0, "Żywność i Supermarket"),
    ("Stek z rostbefu wołowego 250g", 26.99, 2.0, "Żywność i Supermarket"),
    ("Krewetki mrożone 450g", 36.99, 2.0, "Żywność i Supermarket"),
    ("Twaróg półtłusty 250g", 4.49, 2.0, "Żywność i Supermarket"),
    ("Jogurt grecki 400g", 4.29, 2.0, "Żywność i Supermarket"),
    ("Ser Camembert President 120g", 6.99, 3.0, "Żywność i Supermarket"),
    ("Pomidorki koktajlowe 500g", 11.99, 2.0, "Żywność i Supermarket"),
    ("Sałata rzymska 2szt", 7.99, 2.0, "Żywność i Supermarket"),
    ("Winogrona jasne bezpestkowe 500g", 12.99, 2.0, "Żywność i Supermarket"),
    ("Czosnek polski 3szt", 5.99, 1.0, "Żywność i Supermarket"),
    ("Kasza jaglana 1kg", 6.49, 2.0, "Żywność i Supermarket"),
    ("Oliwa z pestek winogron 750ml", 29.99, 1.0, "Żywność i Supermarket"),
    ("Musli owocowe 500g", 10.99, 2.0, "Żywność i Supermarket"),
    ("Kawa rozpuszczalna Jacobs 200g", 32.99, 1.0, "Żywność i Supermarket"),
    ("Herbata czarna Earl Grey 100szt", 18.99, 2.0, "Żywność i Supermarket"),
    ("Sok pomarańczowy 100% 1L", 6.99, 4.0, "Żywność i Supermarket"),
    ("Cukier trzcinowy 1kg", 8.99, 1.0, "Żywność i Supermarket"),
    ("Pistacje prażone solone 250g", 23.74, 1.0, "Żywność i Supermarket"),
]

ALLG_FULL_ITEMS = [
    ("Wkłady filtrujące Dafi Unimax 5+1 szt.", 69.00, 1.0, "Drogeria i Zdrowie"),
    ("Płyn micelarny Garnier 400ml", 21.90, 1.0, "Drogeria i Zdrowie"),
    ("Szampon wzmacniający do włosów 400ml", 16.40, 1.0, "Drogeria i Zdrowie"),
]


def get_transaction_dates(year: int, month: int, daily_count: int = 20) -> List[datetime]:
    """Generate realistic dates for transactions in the target year/month."""
    now = datetime.now(timezone.utc)
    is_current = (year == now.year and month == now.month)
    today_day = now.day if is_current else 28
    max_days = calendar.monthrange(year, month)[1]

    dates = []
    # 1. Income (Day 1 at 09:00)
    dates.append(datetime(year, month, 1, 9, 0, tzinfo=timezone.utc))
    # 2. Rata kredytu (Day 2 at 10:00)
    dates.append(datetime(year, month, min(2, max_days), 10, 0, tzinfo=timezone.utc))
    # 3. Czynsz (Day 3 at 11:30)
    dates.append(datetime(year, month, min(3, max_days), 11, 30, tzinfo=timezone.utc))
    # 4. PGE (Day 4 at 09:30)
    dates.append(datetime(year, month, min(4, max_days), 9, 30, tzinfo=timezone.utc))
    # 5. Orange (Day 4 at 11:00)
    dates.append(datetime(year, month, min(4, max_days), 11, 0, tzinfo=timezone.utc))

    # 20 Daily Transactions
    if is_current and today_day >= 8:
        span_end = min(today_day, max_days)
        for i in range(daily_count):
            d = 4 + int((i / max(1, daily_count - 1)) * (span_end - 4))
            h = 10 + (i % 10)
            m = (i * 17) % 60
            dt = datetime(year, month, d, h, m, tzinfo=timezone.utc)
            if dt > now:
                dt = now - timedelta(hours=i + 1)
            dates.append(dt)
    else:
        span_end = min(26, max_days)
        for i in range(daily_count):
            d = 4 + int((i / max(1, daily_count - 1)) * (span_end - 4))
            h = 10 + (i % 10)
            m = (i * 17) % 60
            dt = datetime(year, month, d, h, m, tzinfo=timezone.utc)
            dates.append(dt)

    return dates


def clean_demo_data(session: Session, user: User) -> None:
    """Delete all budgets, accounts, categories, transactions and allocations owned by demo user."""
    logger.info("Cleaning existing demo data for user %s", user.email)

    memberships = session.exec(select(BudgetMember).where(BudgetMember.user_id == user.id)).all()
    budget_ids = [m.budget_id for m in memberships]

    owned_budgets = session.exec(select(Budget).where(Budget.owner_id == user.id)).all()
    for b in owned_budgets:
        if b.id and b.id not in budget_ids:
            budget_ids.append(b.id)

    for budget_id in budget_ids:
        transactions = session.exec(select(Transaction).where(col(Transaction.budget_id) == budget_id)).all()
        t_ids = [t.id for t in transactions if t.id is not None]
        if t_ids:
            session.exec(delete(TransactionLine).where(col(TransactionLine.transaction_id).in_(t_ids)))
            session.exec(delete(ReceiptScan).where(col(ReceiptScan.transaction_id).in_(t_ids)))
            session.exec(delete(Transaction).where(col(Transaction.id).in_(t_ids)))

        session.exec(delete(EnvelopeAllocation).where(col(EnvelopeAllocation.budget_id) == budget_id))
        session.exec(delete(Account).where(col(Account.budget_id) == budget_id))

        session.exec(
            delete(Category).where(
                col(Category.budget_id) == budget_id,
                col(Category.parent_id).is_not(None)
            )
        )
        session.exec(delete(Category).where(col(Category.budget_id) == budget_id))

        session.exec(delete(BudgetMember).where(col(BudgetMember.budget_id) == budget_id))
        session.exec(delete(Budget).where(col(Budget.id) == budget_id))

    user.default_budget_id = None
    session.add(user)
    session.commit()


def seed_demo_month(
    session: Session,
    budget: Budget,
    demo_user: User,
    cat_map: Dict[str, Category],
    acc_checking: Account,
    acc_cash: Account,
    year: int,
    month: int,
) -> None:
    """Seed envelope allocations and 25 realistic transactions for the specified year/month."""
    logger.info("Seeding demo month %04d-%02d for budget %s", year, month, budget.name)
    assert budget.id is not None

    def get_cat(name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        cat = cat_map.get(name)
        return cat.id if cat else None

    # 1. Envelope Allocations
    for _, _, _, subcats in CATEGORIES_DEF:
        for sub_name, _, _, planned in subcats:
            if planned > 0:
                sub_cat = cat_map.get(sub_name)
                if sub_cat and sub_cat.id:
                    allocation = EnvelopeAllocation(
                        budget_id=budget.id,
                        category_id=sub_cat.id,
                        year=year,
                        month=month,
                        amount=planned,
                    )
                    session.add(allocation)

    session.flush()

    # 2. Transactions & Lines
    now = datetime.now(timezone.utc)
    is_current = (year == now.year and month == now.month)
    dates = get_transaction_dates(year, month, daily_count=20)

    for idx, (merchant, amount, acc_type, t_type, status, cat_name, note, items) in enumerate(TRANSACTIONS_TEMPLATE):
        acc = acc_checking if acc_type == "checking" else acc_cash
        t_date = dates[idx]

        # In non-current months (which do not have staging inbox receipts),
        # use full Biedronka (480.00) and Allegro (107.30) values so every month sums to 6500.00 PLN.
        actual_amount = amount
        actual_items = items
        if not is_current:
            if merchant == "Biedronka" and amount == 368.34:
                actual_amount = 480.00
                actual_items = B2_FULL_ITEMS
            elif merchant == "Allegro" and amount == 92.16:
                actual_amount = 107.30
                actual_items = ALLG_FULL_ITEMS

        t = Transaction(
            merchant_name=merchant,
            date=t_date,
            total_amount=actual_amount,
            currency="PLN",
            type=t_type,
            status=status,
            account_id=acc.id,
            budget_id=budget.id,
            uploaded_by=demo_user.id,
            category_id=get_cat(cat_name),
            note=note,
        )
        session.add(t)
        session.flush()

        for line_name, unit_price, qty, c_name in actual_items:
            session.add(
                TransactionLine(
                    transaction_id=t.id,
                    name=line_name,
                    price=unit_price,
                    quantity=qty,
                    category_id=get_cat(c_name),
                    category_source="auto_categorizer" if c_name else None,
                )
            )

    session.commit()


def ensure_demo_data_for_month(
    session: Session,
    budget_id: int,
    user_id: int,
    year: int,
    month: int,
) -> bool:
    """
    Ensure the demo budget has allocations and realistic transactions for the specified year/month.
    Automatically called on budget summary requests or demo login.
    Returns True if new month data was seeded, False if already present.
    """
    existing_alloc = session.exec(
        select(EnvelopeAllocation).where(
            EnvelopeAllocation.budget_id == budget_id,
            EnvelopeAllocation.year == year,
            EnvelopeAllocation.month == month,
        )
    ).first()

    if existing_alloc:
        return False

    budget = session.get(Budget, budget_id)
    user = session.get(User, user_id)
    if not budget or not user:
        return False

    accounts = session.exec(select(Account).where(Account.budget_id == budget_id)).all()
    acc_checking = next((a for a in accounts if a.type == "checking"), None)
    acc_cash = next((a for a in accounts if a.type == "cash"), None)
    if not acc_checking or not acc_cash:
        return False

    categories = session.exec(select(Category).where(Category.budget_id == budget_id)).all()
    cat_map = {c.name: c for c in categories}

    seed_demo_month(
        session=session,
        budget=budget,
        demo_user=user,
        cat_map=cat_map,
        acc_checking=acc_checking,
        acc_cash=acc_cash,
        year=year,
        month=month,
    )
    return True


def seed_demo_environment(
    session: Session,
    force_reset: bool = False,
    custom_user: Optional[User] = None,
) -> User:
    """
    Seed a complete, idempotent demo environment.
    If custom_user is provided, seeds specifically for that ephemeral demo user.
    If force_reset=False and demo user already exists:
    ensures current month data is present and returns existing user.
    """
    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    prev_year = now.year - 1 if now.month == 1 else now.year
    prev_month = 12 if now.month == 1 else now.month - 1

    if custom_user:
        demo_user = custom_user
        if force_reset:
            clean_demo_data(session, demo_user)
            session.refresh(demo_user)
        elif demo_user.default_budget_id:
            existing_budget = session.get(Budget, demo_user.default_budget_id)
            if existing_budget:
                assert existing_budget.id is not None
                assert demo_user.id is not None
                account_count = session.exec(select(Account).where(col(Account.budget_id) == existing_budget.id)).all()
                if account_count:
                    ensure_demo_data_for_month(session, existing_budget.id, demo_user.id, current_year, current_month)
                    logger.info("Demo environment already seeded for %s, verified current month.", demo_user.email)
                    return demo_user
    else:
        # 1. Ensure Default Demo User exists
        demo_user = session.exec(select(User).where(col(User.email) == settings.DEMO_USER_EMAIL)).first()
        if not demo_user:
            demo_user = User(
                email=settings.DEMO_USER_EMAIL,
                hashed_password=hash_password(DEMO_USER_PASSWORD),
                created_at=now - timedelta(days=60),
            )
            session.add(demo_user)
            session.commit()
            session.refresh(demo_user)
        elif force_reset:
            clean_demo_data(session, demo_user)
            session.refresh(demo_user)
        else:
            if demo_user.default_budget_id:
                existing_budget = session.get(Budget, demo_user.default_budget_id)
                if existing_budget:
                    assert existing_budget.id is not None
                    assert demo_user.id is not None
                    account_count = session.exec(select(Account).where(col(Account.budget_id) == existing_budget.id)).all()
                    if account_count:
                        # Automatically ensure current month is seeded even if previously skipped
                        ensure_demo_data_for_month(session, existing_budget.id, demo_user.id, current_year, current_month)
                        logger.info("Demo environment already seeded for %s, verified current month.", demo_user.email)
                        return demo_user

    # 2. Create Budget & Owner Membership
    assert demo_user.id is not None
    budget = Budget(name=DEMO_BUDGET_NAME, owner_id=demo_user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)

    assert budget.id is not None
    member = BudgetMember(budget_id=budget.id, user_id=demo_user.id, role="owner")
    session.add(member)

    demo_user.default_budget_id = budget.id
    session.add(demo_user)
    session.commit()

    # 3. Create Accounts
    acc_checking = Account(
        name="Konto Główne ROR (mBank)",
        type="checking",
        currency="PLN",
        initial_balance=4250.00,
        current_balance=4250.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    acc_savings = Account(
        name="Konto Oszczędnościowe (ING)",
        type="savings",
        currency="PLN",
        initial_balance=18500.00,
        current_balance=18500.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    acc_cash = Account(
        name="Portfel / Gotówka",
        type="cash",
        currency="PLN",
        initial_balance=320.00,
        current_balance=320.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    session.add(acc_checking)
    session.add(acc_savings)
    session.add(acc_cash)
    session.commit()
    session.refresh(acc_checking)
    session.refresh(acc_savings)
    session.refresh(acc_cash)

    # 4. Create Category Groups & Categories
    cat_map: Dict[str, Category] = {}
    order_idx = 0

    for group_name, g_icon, g_color, subcats in CATEGORIES_DEF:
        group_cat = Category(
            name=group_name,
            icon=g_icon,
            color=g_color,
            is_system=False,
            budget_id=budget.id,
            parent_id=None,
            order_index=order_idx,
        )
        session.add(group_cat)
        session.commit()
        session.refresh(group_cat)
        order_idx += 1

        for sub_name, s_icon, s_color, _ in subcats:
            sub_cat = Category(
                name=sub_name,
                icon=s_icon,
                color=s_color,
                is_system=False,
                budget_id=budget.id,
                parent_id=group_cat.id,
                order_index=order_idx,
            )
            session.add(sub_cat)
            session.commit()
            session.refresh(sub_cat)
            order_idx += 1
            cat_map[sub_name] = sub_cat

    # 5. Seed Previous and Current Month
    seed_demo_month(
        session=session,
        budget=budget,
        demo_user=demo_user,
        cat_map=cat_map,
        acc_checking=acc_checking,
        acc_cash=acc_cash,
        year=prev_year,
        month=prev_month,
    )
    seed_demo_month(
        session=session,
        budget=budget,
        demo_user=demo_user,
        cat_map=cat_map,
        acc_checking=acc_checking,
        acc_cash=acc_cash,
        year=current_year,
        month=current_month,
    )

    # 6. Showcase Staging Receipts in /inbox (Awaiting Verification)
    t1_date = now - timedelta(hours=3)
    t1 = Transaction(
        merchant_name="Biedronka",
        date=t1_date,
        total_amount=84.50,
        currency="PLN",
        type="expense",
        status=TransactionStatus.UNCLEARED,
        account_id=acc_checking.id,
        budget_id=budget.id,
        uploaded_by=demo_user.id,
        category_id=cat_map["Żywność i Supermarket"].id if "Żywność i Supermarket" in cat_map else None,
        note="Paragon ze skanera OCR (oczekuje na potwierdzenie)",
    )
    session.add(t1)
    session.commit()
    session.refresh(t1)
    assert t1.id is not None

    scan1 = ReceiptScan(
        transaction_id=t1.id,
        status=ScanStatus.NEEDS_REVIEW.value,
        needs_review=True,
        validation_message="Sprawdź przypisane kategorie przed zatwierdzeniem",
        raw_ocr_text="Jeronimo Martins Polska S.A. Biedronka... SUMA PLN 84.50",
        reconstructed_lines=[
            "Jeronimo Martins Polska S.A.",
            "BIEDRONKA UL. PROSTA 12",
            "Mleko Wiejskie 3.2% 1L   2 x 3.69 = 7.38 A",
            "Chleb Żytni Krojony 500g 1 x 4.50 = 4.50 A",
            "Kawa Ziarnista Lavazza 1kg 1 x 49.99 = 49.99 A",
            "Jabłka Polskie Gala 1.5kg  1 x 7.49 = 7.49 A",
            "Płyn do naczyń Pur 750ml   1 x 15.14 = 15.14 B",
            "SUMA PLN: 84.50",
        ],
        created_at=t1_date,
    )
    session.add(scan1)

    t1_lines = [
        ("Mleko Wiejskie 3.2% 1L", 3.69, 2.0, "Żywność i Supermarket"),
        ("Chleb Żytni Krojony 500g", 4.50, 1.0, "Żywność i Supermarket"),
        ("Kawa Ziarnista Lavazza 1kg", 49.99, 1.0, "Żywność i Supermarket"),
        ("Jabłka Polskie Gala 1.5kg", 7.49, 1.0, "Żywność i Supermarket"),
        ("Płyn do naczyń Pur 750ml", 15.14, 1.0, "Drogeria i Zdrowie"),
    ]
    for line_name, price, qty, c_name in t1_lines:
        c_id = cat_map[c_name].id if c_name in cat_map else None
        session.add(
            TransactionLine(
                transaction_id=t1.id,
                name=line_name,
                price=price,
                quantity=qty,
                category_id=c_id,
                category_source="auto_categorizer",
            )
        )

    t2_date = now - timedelta(days=1, hours=2)
    t2 = Transaction(
        merchant_name="Lidl",
        date=t2_date,
        total_amount=42.30,
        currency="PLN",
        type="expense",
        status=TransactionStatus.UNCLEARED,
        account_id=acc_checking.id,
        budget_id=budget.id,
        uploaded_by=demo_user.id,
        category_id=cat_map["Żywność i Supermarket"].id if "Żywność i Supermarket" in cat_map else None,
        note="Paragon ze skanera OCR (oczekuje na potwierdzenie)",
    )
    session.add(t2)
    session.commit()
    session.refresh(t2)
    assert t2.id is not None

    scan2 = ReceiptScan(
        transaction_id=t2.id,
        status=ScanStatus.NEEDS_REVIEW.value,
        needs_review=True,
        validation_message="Sprawdź przypisane kategorie przed zatwierdzeniem",
        raw_ocr_text="LIDL SP Z O O SP K... SUMA PLN 42.30",
        reconstructed_lines=[
            "LIDL POLSKA",
            "Masło Pilos Ekstra 200g 2 x 6.99 = 13.98 A",
            "Ser Gouda w plastrach 400g 1 x 12.49 = 12.49 A",
            "Pomidory Gałązka 1kg 1 x 15.83 = 15.83 A",
            "SUMA PLN: 42.30",
        ],
        created_at=t2_date,
    )
    session.add(scan2)

    t2_lines = [
        ("Masło Pilos Ekstra 200g", 6.99, 2.0, "Żywność i Supermarket"),
        ("Ser Gouda w plastrach 400g", 12.49, 1.0, "Żywność i Supermarket"),
        ("Pomidory Gałązka 1kg", 15.83, 1.0, "Żywność i Supermarket"),
    ]
    for line_name, price, qty, c_name in t2_lines:
        c_id = cat_map[c_name].id if c_name in cat_map else None
        session.add(
            TransactionLine(
                transaction_id=t2.id,
                name=line_name,
                price=price,
                quantity=qty,
                category_id=c_id,
                category_source="auto_categorizer",
            )
        )

    session.commit()
    session.refresh(demo_user)
    logger.info("Demo environment successfully seeded for %s (Budget ID: %s)", demo_user.email, budget.id)
    return demo_user


def cleanup_expired_demo_sessions(session: Session, max_age_hours: int = 24) -> int:
    """
    Remove ephemeral demo users and their budgets, transactions, and scan files older than max_age_hours.
    Does not delete the static settings.DEMO_USER_EMAIL.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    ephemeral_users = session.exec(
        select(User).where(
            User.email.startswith("demo_"),
            User.created_at < cutoff,
        )
    ).all()

    removed_count = 0
    for u in ephemeral_users:
        logger.info("Cleaning expired demo user %s (created %s)", u.email, u.created_at)
        user_scans = session.exec(
            select(ReceiptScan).join(Transaction).where(Transaction.uploaded_by == u.id)
        ).all()
        for s in user_scans:
            if s.image_path and os.path.exists(s.image_path) and not s.image_path.startswith("backend/app/static/"):
                try:
                    os.remove(s.image_path)
                except OSError:
                    pass

        clean_demo_data(session, u)
        session.delete(u)
        removed_count += 1

    session.commit()
    logger.info("Removed %d expired demo sessions.", removed_count)
    return removed_count


if __name__ == "__main__":
    from .database import operations_engine

    parser = argparse.ArgumentParser(description="Seed demo environment")
    parser.add_argument("--force-reset", action="store_true", help="Force clean and re-seed demo data")
    args = parser.parse_args()

    with Session(operations_engine) as session:
        user = seed_demo_environment(session, force_reset=args.force_reset)
        print(f"✅ Demo environment ready for {user.email} (Budget ID: {user.default_budget_id})")
