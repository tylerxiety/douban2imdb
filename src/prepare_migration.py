"""
Module for preparing the migration plan from Douban to IMDb.
"""
import os
import json
import logging
from difflib import SequenceMatcher
from tqdm import tqdm
from dotenv import load_dotenv
import re

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
        # Ensure we're using the main show ID, not episode ID
        main_imdb_id = douban_imdb_id.split('/')[0] if '/' in douban_imdb_id else douban_imdb_id
        
        for imdb_movie in imdb_ratings:
            if imdb_movie['imdb_id'] == main_imdb_id:
                return imdb_movie
    
    return None

def find_imdb_match_by_title(douban_movie, imdb_ratings, threshold=0.8):
    """
    Find the best IMDb match by title and year similarity.
    
    Args:
        douban_movie: Movie data from Douban
        imdb_ratings: List of IMDb ratings
        threshold: Minimum similarity score to consider a match
        
    Returns:
        Matching IMDb movie or None if no match found, plus the match score
    """
    best_match = None
    best_score = 0
    
    # Try both English title and original title for matching
    douban_title = douban_movie.get("title", "")
    douban_english_title = douban_movie.get("english_title", "")
    
    for imdb_movie in imdb_ratings:
        imdb_title = imdb_movie.get("title", "")
        
        # Calculate score using original title
        score1 = similarity_score(
            douban_title, 
            imdb_title,
            douban_movie.get("year"), 
            imdb_movie.get("year")
        )
        
        # Calculate score using English title if available
        score2 = 0
        if douban_english_title:
            score2 = similarity_score(
                douban_english_title, 
                imdb_title,
                douban_movie.get("year"), 
                imdb_movie.get("year")
            )
        
        # Use the better of the two scores
        score = max(score1, score2)
        
        if score > best_score:
            best_score = score
            best_match = imdb_movie
    
    # Return the match only if it exceeds the threshold
    if best_score >= threshold:
        if best_score < 1.0:  # Only log if not a perfect match
            logger.info(f"Found title match: {douban_movie.get('title')} -> {best_match.get('title')} (score: {best_score:.2f})")
        return best_match, best_score
    return None, 0

def is_tv_show(title, original_title="", metadata=None):
    """
    Check if a title is likely a TV show based on common patterns or metadata.
    
    Args:
        title: The movie title to check
        original_title: Original title (optional)
        metadata: Additional metadata dictionary (optional)
        
    Returns:
        Boolean indicating if it's likely a TV show
    """
    # Common TV show patterns
    patterns = [
        r'第\s*[一二三四五六七八九十零0-9]+\s*[季期]',  # Chinese season indicators: 第一季, 第1季, etc.
        r'Season\s*[0-9]+',  # English "Season X"
        r'S[0-9]+',  # S1, S2 format
        r'完结篇',  # Final season in Chinese
        r'[Tt]he\s+[Cc]omplete\s+[Ss]eries',  # Complete series
        r'[Ss]eries\s+[0-9]+',  # Series X (British format)
    ]
    
    # Check title
    for pattern in patterns:
        if re.search(pattern, title):
            return True
    
    # Check original title if provided
    if original_title:
        for pattern in patterns:
            if re.search(pattern, original_title):
                return True
    
    # Check metadata if provided
    if metadata:
        # Check if type is explicitly TV
        if metadata.get("type") == "tv":
            return True
        
        # Check IMDb ID - TV shows often have "tt" followed by digits
        imdb_id = metadata.get("imdb_id", "")
        if imdb_id.startswith("tt") and "/episode" in imdb_id:
            return True
    
    return False

def extract_series_name(title):
    """
    Extract the base series name from a title with season information.
    
    Args:
        title: The full title with season information
        
    Returns:
        The base series name without season information
    """
    # Remove season information patterns
    patterns = [
        r'第\s*[一二三四五六七八九十零0-9]+\s*[季期]',  # Chinese season indicators
        r'Season\s*[0-9]+',  # English "Season X"
        r'S[0-9]+',  # S1, S2 format
        r'完结篇',  # Final season in Chinese
        r'[Tt]he\s+[Cc]omplete\s+[Ss]eries',  # Complete series
        r'[Ss]eries\s+[0-9]+',  # Series X (British format)
    ]
    
    clean_title = title
    for pattern in patterns:
        clean_title = re.sub(pattern, '', clean_title).strip()
    
    # Remove trailing separators like ":" or "-" that might be left after removing season info
    clean_title = re.sub(r'[\s:：\-–—]+$', '', clean_title).strip()
    
    return clean_title

def find_imdb_match(douban_movie, imdb_ratings):
    """
    Find the best matching IMDb movie for a Douban movie.
    
    Args:
        douban_movie: Movie data from Douban
        imdb_ratings: List of IMDb ratings
        
    Returns:
        Tuple of (best_match, score), where best_match is the IMDb movie data
        and score is the similarity score between 0 and 1
    """
    # First try matching by IMDb ID (most precise)
    imdb_id_match = find_imdb_match_by_id(douban_movie, imdb_ratings)
    if imdb_id_match:
        # If we found a match by IMDb ID, it's a perfect match (score 1.0)
        return imdb_id_match, 1.0
    
    # Check if this is a TV show
    title = douban_movie.get('title', '')
    original_title = douban_movie.get('original_title', '')
    is_tv = is_tv_show(title, original_title, douban_movie)
    
    # For TV shows, try to match the base series name
    if is_tv:
        logger.info(f"Detected TV show: {title}")
        series_name = extract_series_name(title)
        logger.info(f"Extracted series name: {series_name}")
        
        # Try to find matches based on the series name
        best_match = None
        best_score = 0
        
        for imdb_movie in imdb_ratings:
            imdb_title = imdb_movie.get('title', '')
            
            # Some IMDb TV shows have season info in the title too
            if is_tv_show(imdb_title, imdb_movie.get('original_title', ''), imdb_movie):
                imdb_series_name = extract_series_name(imdb_title)
                score = similarity_score(
                    series_name, 
                    imdb_series_name,
                    douban_movie.get('year'),
                    imdb_movie.get('year')
                )
            else:
                # IMDb might just have the series name without season info
                score = similarity_score(
                    series_name, 
                    imdb_title,
                    douban_movie.get('year'),
                    imdb_movie.get('year')
                )
            
            if score > best_score and score >= 0.7:  # Use slightly lower threshold for TV shows
                best_score = score
                best_match = imdb_movie
        
        if best_match:
            logger.info(f"Found TV show match by series name: {douban_movie.get('title')} -> {best_match.get('title')} (score: {best_score:.2f})")
            return best_match, best_score
    
    # If not a TV show or no match found, fallback to title similarity
    title_match_result = find_imdb_match_by_title(douban_movie, imdb_ratings)
    return title_match_result

def extract_tv_show_details(title, original_title=""):
    """
    Extract TV show details including base name and season number.
    
    Args:
        title: The title to analyze
        original_title: Original title (optional)
        
    Returns:
        Dictionary with base_title and season_number
    """
    # Default values
    details = {
        "base_title": title,
        "season_number": 0
    }
    
    # Extract season number from title if possible
    season_match = re.search(r"[Ss]eason\s+(\d+)|S(\d+)|第(\d+)季|第([一二三四五六七八九十]+)季", title)
    if season_match:
        # Get the first non-None group from the match
        for group in season_match.groups():
            if group is not None:
                # Convert Chinese numerals to digits if needed
                if group in "一二三四五六七八九十":
                    cn_numeral_map = {
                        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10
                    }
                    details["season_number"] = cn_numeral_map.get(group, 0)
                else:
                    try:
                        details["season_number"] = int(group)
                    except ValueError:
                        details["season_number"] = 0
                break
    
    # Extract base title (remove season info)
    details["base_title"] = extract_series_name(title)
    
    return details

def prepare_migration_plan(douban_export_path=DOUBAN_EXPORT_PATH, imdb_export_path=IMDB_EXPORT_PATH, save_path=MIGRATION_PLAN_PATH):
    """
    Prepare a plan to migrate Douban ratings to IMDb.
    
    Returns a dictionary with migration details
    """
    # Load data
    douban_ratings = []
    if os.path.exists(douban_export_path):
        with open(douban_export_path, 'r', encoding='utf-8') as f:
            douban_ratings = json.load(f)
            logger.info(f"Loaded {len(douban_ratings)} Douban ratings from {douban_export_path}")
    else:
        logger.error(f"Douban ratings file not found at {douban_export_path}")
        return None
    
    imdb_ratings = []
    if os.path.exists(imdb_export_path):
        with open(imdb_export_path, 'r', encoding='utf-8') as f:
            imdb_ratings = json.load(f)
            logger.info(f"Loaded {len(imdb_ratings)} IMDb ratings from {imdb_export_path}")
    
    # Create migration plan
    migration_plan = {
        "to_migrate": [],  # Movies we'll migrate
        "already_rated": [],  # Movies already rated on IMDb
        "stats": {
            "total_douban_ratings": len(douban_ratings),
            "total_imdb_ratings": len(imdb_ratings),
            "matched_with_existing_imdb": 0,  # Movies matched with existing IMDb ratings
            "has_imdb_id_to_migrate": 0,     # Movies with IMDb ID that need to be migrated
            "matched_by_title": 0,            # Movies matched by title similarity
            "matched_by_manual": 0,           # Movies matched manually
            "not_matched": 0,                 # Movies not matched
            "tv_shows_combined": 0            # TV shows combined from multiple seasons
        }
    }
    
    # Build an index of IMDb ratings
    imdb_index = {movie["imdb_id"]: movie for movie in imdb_ratings if "imdb_id" in movie}
    
    # Pre-process all movies to detect TV shows and extract details
    # This avoids repeated processing of the same titles
    logger.info("Pre-processing movies to identify TV shows...")
    movie_details = {}
    for movie in douban_ratings:
        if not movie.get("title"):
            continue
        
        movie_id = movie.get("douban_id", "") or movie.get("imdb_id", "")
        if not movie_id:
            continue
            
        title = movie.get("title", "")
        original_title = movie.get("original_title", "")
        
        # Determine if it's a TV show and extract details upfront
        is_tv = is_tv_show(title, original_title, movie)
        tv_details = extract_tv_show_details(title, original_title)
        
        movie_details[movie_id] = {
            "movie": movie,
            "is_tv": is_tv or tv_details["season_number"] > 0,
            "base_title": tv_details["base_title"],
            "season_number": tv_details["season_number"],
            "processed": False
        }
    
    # First, identify TV shows and group them
    # TV shows can have multiple seasons with different ratings on Douban
    tv_shows = {}
    logger.info("Grouping TV shows by base title...")
    
    # Step 1: Group obvious TV shows (those with season markers or TV type)
    for movie_id, details in movie_details.items():
        movie = details["movie"]
        is_tv = details["is_tv"]
        
        if is_tv and "imdb_id" in movie:
            base_title = details["base_title"]
            show_key = base_title.lower()
            
            # Initialize the show entry if it doesn't exist
            if show_key not in tv_shows:
                tv_shows[show_key] = {
                    "seasons": [],
                    "base_title": base_title,
                    "base_original_title": extract_series_name(movie.get("original_title", "")) if movie.get("original_title") else "",
                    "year": movie.get("year", ""),
                    "type": "tv",
                    "first_season_imdb_id": None
                }
                
            # Add this season to the show's seasons list
            season_info = {
                "title": movie.get("title", ""),
                "original_title": movie.get("original_title", ""),
                "rating": movie.get("rating", 0),
                "douban_id": movie.get("douban_id", ""),
                "imdb_id": movie["imdb_id"],
                "season_number": details["season_number"]
            }
            tv_shows[show_key]["seasons"].append(season_info)
            details["processed"] = True
    
    # Step 2: Build an index of movies by base title for faster lookups
    logger.info("Building TV show title index...")
    base_title_index = {}
    for movie_id, details in movie_details.items():
        if details["processed"]:
            continue
            
        if "imdb_id" not in details["movie"]:
            continue
            
        base_title = details["base_title"].lower()
        if base_title not in base_title_index:
            base_title_index[base_title] = []
        base_title_index[base_title].append(details)
    
    # Step 3: Find potential TV shows by grouping similar base titles
    logger.info("Finding potential TV shows...")
    for base_title, title_group in base_title_index.items():
        # Skip single movies
        if len(title_group) <= 1:
            continue
            
        # Check if any in the group is already identified as a TV show
        has_tv_indicator = any(details["is_tv"] for details in title_group)
        
        if has_tv_indicator:
            # This group likely contains TV show seasons
            # Create a TV show entry if it doesn't exist
            if base_title not in tv_shows:
                first_movie = title_group[0]["movie"]
                tv_shows[base_title] = {
                    "seasons": [],
                    "base_title": title_group[0]["base_title"],
                    "base_original_title": extract_series_name(first_movie.get("original_title", "")) if first_movie.get("original_title") else "",
                    "year": first_movie.get("year", ""),
                    "type": "tv",
                    "first_season_imdb_id": None
                }
                
            # Add all movies in the group as seasons
            for details in title_group:
                movie = details["movie"]
                season_info = {
                    "title": movie.get("title", ""),
                    "original_title": movie.get("original_title", ""),
                    "rating": movie.get("rating", 0),
                    "douban_id": movie.get("douban_id", ""),
                    "imdb_id": movie["imdb_id"],
                    "season_number": details["season_number"]
                }
                tv_shows[base_title]["seasons"].append(season_info)
                details["processed"] = True
            
            logger.info(f"Identified potential TV show: {tv_shows[base_title]['base_title']} with {len(title_group)} seasons")
    
    # Sort seasons by season number and find the main IMDb ID
    logger.info("Processing TV shows...")
    for show_key, show_data in tv_shows.items():
        # Sort seasons by season number
        show_data["seasons"].sort(key=lambda x: x["season_number"])
        
        # The first season (or the first entry if season numbers aren't specified)
        # is most likely to have the main series IMDb ID
        if show_data["seasons"]:
            # Get the IMDb ID from the first season, ensuring it's the main show ID not an episode ID
            first_season_imdb_id = show_data["seasons"][0]["imdb_id"]
            main_show_id = first_season_imdb_id.split('/')[0] if '/' in first_season_imdb_id else first_season_imdb_id
            show_data["first_season_imdb_id"] = main_show_id
    
    # Count for correct matching stats
    matched_with_existing_imdb = 0
    has_imdb_id_to_migrate = 0
    title_matched_movies = 0
    not_matched_movies = 0
    
    # Process TV shows to create single entries with averaged ratings
    logger.info("Creating migration items for TV shows...")
    for show_key, show_data in tv_shows.items():
        if len(show_data["seasons"]) >= 1:  # Process even single-season shows to normalize the IMDb ID
            # Calculate average rating across all seasons
            total_rating = sum(season.get("rating", 0) for season in show_data["seasons"])
            average_rating = round(total_rating / len(show_data["seasons"]), 1)
            
            main_imdb_id = show_data["first_season_imdb_id"]
            seasons_text = f"Average of {len(show_data['seasons'])} seasons" if len(show_data["seasons"]) > 1 else "Single season"
            
            if len(show_data["seasons"]) > 1:
                logger.info(f"Found TV show with multiple seasons: {show_data['base_title']} - {len(show_data['seasons'])} seasons, using main ID: {main_imdb_id}")
            
            # Create a combined TV show entry
            combined_show = {
                "title": show_data["base_title"],
                "original_title": show_data["base_original_title"],
                "year": show_data["year"],
                "rating": average_rating,
                "imdb_id": main_imdb_id,
                "type": "tv",
                "douban_id": show_data["seasons"][0].get("douban_id", ""),  # Use first season's Douban ID
                "seasons_info": seasons_text
            }
            
            # Check if already rated on IMDb
            if main_imdb_id in imdb_index:
                imdb_movie = imdb_index[main_imdb_id]
                migration_item = {
                    "douban": combined_show,
                    "imdb": imdb_movie,
                    "similarity_score": 1.0,  # Perfect match by ID
                    "douban_rating": average_rating,
                    "imdb_rating": convert_douban_to_imdb_rating(average_rating)
                }
                migration_plan["already_rated"].append(migration_item)
                matched_with_existing_imdb += 1  # Truly matched with an existing IMDb rating
            else:
                # Add to migration list
                migration_item = {
                    "douban": combined_show,
                    "imdb": {"imdb_id": main_imdb_id},
                    "similarity_score": 1.0,
                    "douban_rating": average_rating,
                    "imdb_rating": convert_douban_to_imdb_rating(average_rating)
                }
                migration_plan["to_migrate"].append(migration_item)
                has_imdb_id_to_migrate += 1  # Has IMDb ID but needs to be migrated
            
            if len(show_data["seasons"]) > 1:
                migration_plan["stats"]["tv_shows_combined"] += 1
            
            # Mark all seasons as processed by imdb_id
            processed_imdb_ids = set(season.get("imdb_id") for season in show_data["seasons"])
            
            # Mark movies as processed
            for movie in douban_ratings:
                if movie.get("imdb_id") in processed_imdb_ids:
                    movie["_processed_as_tv_show"] = True
    
    # Now process regular movies and TV shows with a single season
    logger.info("Processing remaining movies...")
    for movie in douban_ratings:
        # Skip movies already processed as part of a TV show
        if movie.get("_processed_as_tv_show", False):
            continue
            
        if "imdb_id" in movie:
            # For TV shows, ensure we're using the main show ID
            imdb_id = movie["imdb_id"].split('/')[0] if '/' in movie["imdb_id"] else movie["imdb_id"]
            
            # Check if already rated on IMDb
            if imdb_id in imdb_index:
                imdb_movie = imdb_index[imdb_id]
                migration_item = {
                    "douban": movie,
                    "imdb": imdb_movie,
                    "similarity_score": 1.0,  # Perfect match by ID
                    "douban_rating": movie.get("rating", 0),
                    "imdb_rating": convert_douban_to_imdb_rating(movie.get("rating", 0))
                }
                migration_plan["already_rated"].append(migration_item)
                matched_with_existing_imdb += 1
            else:
                # Add to migration list
                migration_item = {
                    "douban": movie,
                    "imdb": {"imdb_id": imdb_id},
                    "similarity_score": 1.0,
                    "douban_rating": movie.get("rating", 0),
                    "imdb_rating": convert_douban_to_imdb_rating(movie.get("rating", 0))
                }
                migration_plan["to_migrate"].append(migration_item)
                has_imdb_id_to_migrate += 1
        else:
            # Try to find a match by title
            imdb_match, similarity = find_imdb_match_by_title(movie, imdb_ratings)
            if imdb_match:
                # Found a match by title
                migration_item = {
                    "douban": movie,
                    "imdb": imdb_match,
                    "similarity_score": similarity,
                    "douban_rating": movie.get("rating", 0),
                    "imdb_rating": convert_douban_to_imdb_rating(movie.get("rating", 0))
                }
                migration_plan["already_rated"].append(migration_item)
                title_matched_movies += 1
            else:
                not_matched_movies += 1
    
    # Update the stats with correct counts
    migration_plan["stats"]["matched_with_existing_imdb"] = matched_with_existing_imdb
    migration_plan["stats"]["has_imdb_id_to_migrate"] = has_imdb_id_to_migrate
    migration_plan["stats"]["matched_by_title"] = title_matched_movies
    migration_plan["stats"]["not_matched"] = not_matched_movies
    
    # Calculate total for logging purposes
    total_with_imdb_ids = matched_with_existing_imdb + has_imdb_id_to_migrate
    
    # Sanity check: ensure the counts add up correctly
    total_processed = len(migration_plan["to_migrate"]) + len(migration_plan["already_rated"])
    total_matched = total_with_imdb_ids + title_matched_movies
    
    # If there's a mismatch, log it and adjust
    if total_processed != total_matched + not_matched_movies:
        logger.warning(f"Count mismatch: total processed ({total_processed}) != total matched ({total_matched}) + not matched ({not_matched_movies})")
        logger.warning(f"This suggests an accounting error in our statistics.")
    
    # Print statistics
    logger.info(f"Migration plan prepared:")
    logger.info(f"- {len(migration_plan['to_migrate'])} movies to migrate")
    logger.info(f"- {len(migration_plan['already_rated'])} movies already rated")
    logger.info(f"- {matched_with_existing_imdb} movies matched with existing IMDb ratings")
    logger.info(f"- {has_imdb_id_to_migrate} movies with IMDb IDs (need to be migrated)")
    logger.info(f"- {title_matched_movies} movies matched by title")
    logger.info(f"- {not_matched_movies} movies not matched")
    logger.info(f"- {migration_plan['stats']['tv_shows_combined']} TV shows combined from multiple seasons")
    
    # Save migration plan
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(migration_plan, f, ensure_ascii=False, indent=2)
        logger.info(f"Migration plan saved to {save_path}")
    
    return migration_plan

if __name__ == "__main__":
    if prepare_migration_plan():
        print(f"Successfully prepared migration plan at {MIGRATION_PLAN_PATH}")
    else:
        print("Failed to prepare migration plan. Check the log for details.") 