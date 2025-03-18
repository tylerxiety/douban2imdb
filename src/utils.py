"""
Utility functions for Douban to IMDb rating migration.
"""
import os
import json
import logging
import random
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure logs directory exists
Path("logs").mkdir(exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join("logs", "douban2imdb.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("douban2imdb")

# Load environment variables
load_dotenv()

def ensure_data_dir():
    """Ensure the data directory exists."""
    Path("data").mkdir(exist_ok=True)
    
    # Also ensure logs directories exist
    Path("logs").mkdir(exist_ok=True)
    Path("debug_logs").mkdir(exist_ok=True)

def save_json(data, filepath):
    """Save data to a JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Data saved to {filepath}")

def load_json(filepath):
    """Load data from a JSON file."""
    if not os.path.exists(filepath):
        logger.warning(f"File {filepath} does not exist")
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    logger.info(f"Data loaded from {filepath}")
    return data

def convert_douban_to_imdb_rating(douban_rating):
    """
    Convert Douban rating (1-5 scale) to IMDb rating (1-10 scale).
    
    Args:
        douban_rating: Rating on Douban scale (1-5)
        
    Returns:
        Rating on IMDb scale (1-10)
    """
    if douban_rating is None:
        return None
    
    # Simple linear mapping: double the Douban rating
    # Douban 1 -> IMDb 2
    # Douban 2 -> IMDb 4
    # Douban 3 -> IMDb 6
    # Douban 4 -> IMDb 8
    # Douban 5 -> IMDb 10
    imdb_rating = int(douban_rating * 2)
    
    # Ensure rating is within IMDb's 1-10 range
    return max(1, min(10, imdb_rating))

# Alias for backward compatibility
douban_to_imdb_rating = convert_douban_to_imdb_rating

def normalize_movie_title(title):
    """
    Normalize movie title for better matching between platforms.
    
    Args:
        title: Movie title to normalize
        
    Returns:
        Normalized title
    """
    # Remove common punctuation and lowercase
    title = title.lower()
    for char in [',', '.', ':', ';', '-', '!', '?', '(', ')', '[', ']', '{', '}', '"', "'"]:
        title = title.replace(char, '')
    
    # Remove common words that might be different between platforms
    words_to_remove = ['the', 'a', 'an']
    words = title.split()
    words = [word for word in words if word not in words_to_remove]
    
    return ' '.join(words).strip()

# Anti-scraping utilities
def random_sleep(min_seconds=1, max_seconds=3):
    """
    Sleep for a random amount of time between min_seconds and max_seconds.
    Helps avoid detection by making requests appear more human-like.
    
    Args:
        min_seconds: Minimum sleep time in seconds
        max_seconds: Maximum sleep time in seconds
    """
    sleep_time = min_seconds + (max_seconds - min_seconds) * random.random()
    time.sleep(sleep_time)
    return sleep_time

def get_random_user_agent():
    """
    Return a random user agent from a predefined list.
    Helps avoid detection by rotating user agents.
    
    Returns:
        A random user agent string
    """
    user_agents = [
        # Chrome on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        # Chrome on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        # Firefox on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
        # Safari on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59"
    ]
    return random.choice(user_agents)

def exponential_backoff(attempt, base_delay=1, max_delay=60):
    """
    Calculate delay using exponential backoff algorithm.
    Useful for retrying requests after failures.
    
    Args:
        attempt: The current attempt number (0-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
    
    Returns:
        Delay time in seconds
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = random.uniform(0, 0.1 * delay)  # Add up to 10% jitter
    return delay + jitter 