from app.models import ProductCategoryCache, User, Category
from sqlmodel import select
from app.cache_service import normalize_name, fuzzy_match_cache, save_to_cache

def test_normalize_name():
    assert normalize_name("Mleko 3.2%") == "mleko 32"
    assert normalize_name("  Bułka    Kajzerka  ") == "bułka kajzerka"
    assert normalize_name("Kiełbasa Śląska (kg)") == "kiełbasa śląska kg"
    assert normalize_name("") == ""
    assert normalize_name("---***///") == ""

def test_fuzzy_match_cache_empty(session):
    user = User(email="test@test.com", hashed_password="hash")
    session.add(user)
    session.commit()
    assert user.id is not None
    
    hits, misses = fuzzy_match_cache(session, user.id, ["Mleko", "Chleb"])
    assert hits == {}
    assert misses == ["Mleko", "Chleb"]

def test_save_and_match_cache(session):
    user = User(email="test2@test.com", hashed_password="hash")
    cat = Category(name="Jedzenie", budget_id=1)
    session.add(user)
    session.add(cat)
    session.commit()
    assert user.id is not None
    assert cat.id is not None
    
    save_to_cache(session, user.id, {
        "Mleko Łaciate 3.2%": cat.id,
        "Chleb wiejski": cat.id
    })
    
    hits, misses = fuzzy_match_cache(session, user.id, ["Mleko Łaciate 3.2%", "Woda"])
    assert hits == {"Mleko Łaciate 3.2%": cat.id}
    assert misses == ["Woda"]
    
    hits, misses = fuzzy_match_cache(session, user.id, ["Mleko laciate 32", "Chleb wiejski krojony"])
    assert "Mleko laciate 32" in hits
    assert hits["Mleko laciate 32"] == cat.id

def test_save_to_cache_duplicates(session):
    user = User(email="test3@test.com", hashed_password="hash")
    cat = Category(name="Jedzenie", budget_id=1)
    session.add(user)
    session.add(cat)
    session.commit()
    assert user.id is not None
    assert cat.id is not None
    
    save_to_cache(session, user.id, {"Mleko": cat.id})
    save_to_cache(session, user.id, {"Mleko": cat.id, "MLEKO": cat.id})
    
    entries = session.exec(select(ProductCategoryCache).where(ProductCategoryCache.user_id == user.id)).all()
    assert len(entries) == 1
