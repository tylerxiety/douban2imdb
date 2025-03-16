"""
Module for preparing the migration plan from Douban to IMDb.
"""
import os
import json
import logging
from difflib import SequenceMatcher
from tqdm import tqdm
from dotenv import load_dotenv

from utils import load_json, save_json, normalize_movie_title, convert_douban_to_imdb_rating, logger

# Load environment variables
load_dotenv()

# Paths
DOUBAN_EXPORT_PATH = os.getenv("DOUBAN_EXPORT_PATH", "data/douban_ratings.json")
IMDB_EXPORT_PATH = os.getenv("IMDB_EXPORT_PATH", "data/imdb_ratings.json")
MIGRATION_PLAN_PATH = os.getenv("MIGRATION_PLAN_PATH", "data/migration_plan.json")

def similarity_score(title1, title2, year1=None, year2=None):
    """
    Calculate similarity score between two movie titles.
    If years are provided, they are factored into the score.
    
    Args:
        title1: First movie title
        title2: Second movie title
        year1: Year of first movie (optional)
        year2: Year of second movie (optional)
        
    Returns:
        Similarity score between 0 and 1
    """
    # Normalize titles
    norm_title1 = normalize_movie_title(title1)
    norm_title2 = normalize_movie_title(title2)
    
    # Calculate title similarity using SequenceMatcher
    title_similarity = SequenceMatcher(None, norm_title1, norm_title2).ratio()
    
    # If years are provided and they match, increase the score
    year_bonus = 0
    if year1 and year2 and year1 == year2:
        year_bonus = 0.2
    
    # Final score (capped at 1.0)
    return min(title_similarity + year_bonus, 1.0)

def find_imdb_match_by_id(douban_movie, imdb_ratings):
    """
    Find a matching IMDb movie by IMDb ID.
    
    Args:
        douban_movie: Movie data from Douban
        imdb_ratings: List of IMDb ratings
        
    Returns:
        Matching IMDb movie or None if no match found
    """
    # If we have an IMDb ID from Douban, use it for direct matching
    if 'imdb_id' in douban_movie and douban_movie['imdb_id']:
        douban_imdb_id = douban_movie['imdb_id']
        for imdb_movie in imdb_ratings:
            if imdb_movie['imdb_id'] == douban_imdb_id:
                return imdb_movie, 1.0  # Perfect match score
    
    return None, 0

def find_imdb_match_by_title(douban_movie, imdb_ratings, threshold=0.8):
    """
    Find the best IMDb match by title and year similarity.
    
    Args:
        douban_movie: Movie data from Douban
        imdb_ratings: List of IMDb ratings
        threshold: Minimum similarity score to consider a match
        
    Returns:
        Matching IMDb movie or None if no match found
    """
    best_match = None
    best_score = 0
    
    for imdb_movie in imdb_ratings:
        score = similarity_score(
            douban_movie["title"], 
            imdb_movie["title"],
            douban_movie.get("year"), 
            imdb_movie.get("year")
        )
        
        if score > best_score:
            best_score = score
            best_match = imdb_movie
    
    # Return the match only if it exceeds the threshold
    if best_score >= threshold:
        return best_match, best_score
    return None, 0

def find_imdb_match(douban_movie, imdb_ratings, threshold=0.8):
    """
    Find the best IMDb match for a Douban movie.
    First tries to match by IMDb ID, then falls back to title matching.
    
    Args:
        douban_movie: Movie data from Douban
        imdb_ratings: List of IMDb ratings
        threshold: Minimum similarity score to consider a match for title matching
        
    Returns:
        Matching IMDb movie or None if no match found, plus the match score
    """
    # First try direct IMDb ID matching
    match, score = find_imdb_match_by_id(douban_movie, imdb_ratings)
    if match:
        logger.info(f"Found perfect IMDb ID match for {douban_movie['title']}")
        return match, score
    
    # Fall back to title similarity matching
    return find_imdb_match_by_title(douban_movie, imdb_ratings, threshold)

def prepare_migration_plan():
    """Prepare the migration plan by comparing Douban and IMDb ratings."""
    # Load ratings
    douban_ratings = load_json(DOUBAN_EXPORT_PATH)
    imdb_ratings = load_json(IMDB_EXPORT_PATH)
    
    if not douban_ratings or not imdb_ratings:
        logger.error("Failed to load ratings data")
        return False
    
    logger.info(f"Loaded {len(douban_ratings)} Douban ratings and {len(imdb_ratings)} IMDb ratings")
    
    # Create migration plan
    migration_plan = {
        "to_migrate": [],  # Movies to migrate
        "already_rated": [],  # Movies already rated on IMDb
        "conversion_stats": {  # Statistics for rating conversion
            "total": 0,
            "by_douban_rating": {},
            "by_imdb_rating": {}
        },
        "match_stats": {  # Statistics about matching methods
            "total": 0,
            "by_imdb_id": 0,
            "by_title_similarity": 0,
            "no_match": 0
        }
    }
    
    # Find matches and prepare migration plan
    for douban_movie in tqdm(douban_ratings, desc="Preparing migration plan"):
        migration_plan["match_stats"]["total"] += 1
        
        # Find matching IMDb movie
        imdb_match, score = find_imdb_match(douban_movie, imdb_ratings)
        
        # Update match statistics
        if imdb_match:
            if score == 1.0 and douban_movie.get('imdb_id'):  # Perfect match by IMDb ID
                migration_plan["match_stats"]["by_imdb_id"] += 1
            else:  # Match by title similarity
                migration_plan["match_stats"]["by_title_similarity"] += 1
        else:
            migration_plan["match_stats"]["no_match"] += 1
        
        # Convert Douban rating to IMDb scale
        douban_rating = douban_movie.get("rating")
        if douban_rating:
            imdb_equivalent = convert_douban_to_imdb_rating(douban_rating)
            
            # Add to conversion stats
            migration_plan["conversion_stats"]["total"] += 1
            
            # Stats by Douban rating
            douban_key = str(douban_rating)
            if douban_key not in migration_plan["conversion_stats"]["by_douban_rating"]:
                migration_plan["conversion_stats"]["by_douban_rating"][douban_key] = {
                    "count": 0,
                    "imdb_equivalent": imdb_equivalent
                }
            migration_plan["conversion_stats"]["by_douban_rating"][douban_key]["count"] += 1
            
            # Stats by IMDb rating
            imdb_key = str(imdb_equivalent)
            if imdb_key not in migration_plan["conversion_stats"]["by_imdb_rating"]:
                migration_plan["conversion_stats"]["by_imdb_rating"][imdb_key] = {
                    "count": 0
                }
            migration_plan["conversion_stats"]["by_imdb_rating"][imdb_key]["count"] += 1
        
        # If we have a match on IMDb already
        if imdb_match:
            # Check if the movie has a different rating on IMDb
            migration_item = {
                "douban": douban_movie,
                "imdb": imdb_match,
                "similarity_score": score,
                "matched_by_imdb_id": score == 1.0 and douban_movie.get('imdb_id') is not None,
                "douban_rating": douban_rating,
                "imdb_rating": imdb_match.get("rating"),
                "imdb_equivalent": imdb_equivalent if douban_rating else None
            }
            
            migration_plan["already_rated"].append(migration_item)
        else:
            # Movie not found on IMDb, add to migration list
            migration_item = {
                "douban": douban_movie,
                "douban_rating": douban_rating,
                "imdb_equivalent": imdb_equivalent if douban_rating else None
            }
            
            migration_plan["to_migrate"].append(migration_item)
    
    # Sort by rating (higher ratings first) for migration efficiency
    migration_plan["to_migrate"].sort(
        key=lambda x: x.get("imdb_equivalent", 0) if x.get("imdb_equivalent") else 0, 
        reverse=True
    )
    
    # Save migration plan
    save_json(migration_plan, MIGRATION_PLAN_PATH)
    
    # Print summary
    to_migrate_count = len(migration_plan["to_migrate"])
    already_rated_count = len(migration_plan["already_rated"])
    total_count = to_migrate_count + already_rated_count
    
    logger.info(f"Migration plan prepared:")
    logger.info(f"  Total movies: {total_count}")
    logger.info(f"  To migrate: {to_migrate_count} ({to_migrate_count/total_count*100:.1f}%)")
    logger.info(f"  Already rated on IMDb: {already_rated_count} ({already_rated_count/total_count*100:.1f}%)")
    
    # Print matching statistics
    logger.info(f"Matching statistics:")
    logger.info(f"  Total movies processed: {migration_plan['match_stats']['total']}")
    logger.info(f"  Matched by IMDb ID: {migration_plan['match_stats']['by_imdb_id']} ({migration_plan['match_stats']['by_imdb_id']/migration_plan['match_stats']['total']*100:.1f}%)")
    logger.info(f"  Matched by title similarity: {migration_plan['match_stats']['by_title_similarity']} ({migration_plan['match_stats']['by_title_similarity']/migration_plan['match_stats']['total']*100:.1f}%)")
    logger.info(f"  No match found: {migration_plan['match_stats']['no_match']} ({migration_plan['match_stats']['no_match']/migration_plan['match_stats']['total']*100:.1f}%)")
    
    logger.info(f"Migration plan saved to {MIGRATION_PLAN_PATH}")
    
    return True

if __name__ == "__main__":
    if prepare_migration_plan():
        print(f"Successfully prepared migration plan at {MIGRATION_PLAN_PATH}")
    else:
        print("Failed to prepare migration plan. Check the log for details.") 