# backend/app/cache_service.py
import re
from typing import Dict, List, Tuple
from rapidfuzz import process, fuzz
from sqlmodel import Session, select, col
from datetime import datetime, timezone

from .models import ProductCategoryCache

def normalize_name(name: str) -> str:
    """Lowercases, trims, and strips special characters from the product name."""
    if not name:
        return ""
    name = name.lower()
    # Remove all non-alphanumeric characters except spaces
    name = re.sub(r'[^\w\s]', '', name)
    # Replace multiple spaces with a single space and trim
    return re.sub(r'\s+', ' ', name).strip()

def fuzzy_match_cache(db_session: Session, user_id: int, item_names: List[str], threshold: int = 85) -> Tuple[Dict[str, int], List[str]]:
    """
    Looks up items in the user's category cache using fuzzy matching.
    
    Returns:
        Tuple containing:
        - Dict mapping original item names to their cache-resolved category_id.
        - List of original item names that were NOT found in the cache (misses).
    """
    if not item_names:
        return {}, []

    # Deduplicate item_names preserving original order
    item_names = list(dict.fromkeys(item_names))

    # Fetch all cached entries for the user
    # Note: For 10k entries, fetching them all into memory takes ~10ms
    cached_entries = db_session.exec(
        select(ProductCategoryCache).where(ProductCategoryCache.user_id == user_id)
    ).all()

    if not cached_entries:
        return {}, item_names

    # Create mapping of normalized names to cache row objects
    cache_dict = {entry.normalized_name: entry for entry in cached_entries}
    cache_keys = list(cache_dict.keys())

    hits: Dict[str, int] = {}
    misses: List[str] = []
    rows_to_update: List[ProductCategoryCache] = []

    for name in item_names:
        norm_name = normalize_name(name)
        if not norm_name:
            misses.append(name)
            continue
            
        # Rapidfuzz exact or fuzzy match
        match = process.extractOne(norm_name, cache_keys, scorer=fuzz.ratio, score_cutoff=threshold)
        
        if match:
            matched_key = match[0]
            matched_entry = cache_dict[matched_key]
            hits[name] = matched_entry.category_id
            
            # Increment hit count and update timestamp
            matched_entry.hit_count += 1
            matched_entry.updated_at = datetime.now(timezone.utc)
            rows_to_update.append(matched_entry)
        else:
            misses.append(name)

    # Batch update hit counts
    if rows_to_update:
        db_session.add_all(rows_to_update)
        db_session.commit()

    return hits, misses

def save_to_cache(db_session: Session, user_id: int, mappings: Dict[str, int]) -> None:
    """
    Saves new product category mappings to the cache.
    Mappings should be original_name -> category_id.
    """
    if not mappings:
        return

    # Fetch existing normalized names to avoid IntegrityError
    normalized_keys = [normalize_name(k) for k in mappings.keys() if normalize_name(k)]
    if not normalized_keys:
        return
        
    existing_entries = db_session.exec(
        select(ProductCategoryCache).where(
            ProductCategoryCache.user_id == user_id,
            col(ProductCategoryCache.normalized_name).in_(normalized_keys)
        )
    ).all()
    
    existing_names = {entry.normalized_name for entry in existing_entries}
    
    new_entries = []
    for original_name, category_id in mappings.items():
        norm_name = normalize_name(original_name)
        if not norm_name or norm_name in existing_names:
            continue
            
        new_entries.append(
            ProductCategoryCache(
                user_id=user_id,
                normalized_name=norm_name,
                original_name=original_name,
                category_id=category_id,
                hit_count=1,
            )
        )
        existing_names.add(norm_name)  # Prevent duplicates within the same batch

    if new_entries:
        db_session.add_all(new_entries)
        db_session.commit()
