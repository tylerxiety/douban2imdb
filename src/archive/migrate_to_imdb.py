"""
Module for migrating movie ratings from Douban to IMDb.
"""
import os
import time
import logging
import json
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
import chromedriver_autoinstaller
from tqdm import tqdm
from dotenv import load_dotenv

from utils import load_json, save_json, logger, random_sleep, get_random_user_agent, exponential_backoff
from export_imdb import login_to_imdb

# Load environment variables
load_dotenv()

# IMDb account info
IMDB_USERNAME = os.getenv("IMDB_USERNAME")
IMDB_PASSWORD = os.getenv("IMDB_PASSWORD")
MIGRATION_PLAN_PATH = os.getenv("MIGRATION_PLAN_PATH", "data/migration_plan.json")
MIGRATION_RESULTS_PATH = "data/migration_results.json"

# Constants
MAX_MOVIES_PER_SESSION = int(os.getenv("MAX_MOVIES_PER_SESSION", "15"))  # Reduced from 50 to avoid detection
COOLDOWN_MIN = float(os.getenv("COOLDOWN_MIN", "3.0"))  # Min seconds between actions
COOLDOWN_MAX = float(os.getenv("COOLDOWN_MAX", "8.0"))  # Max seconds between actions
SEARCH_COOLDOWN_MIN = float(os.getenv("SEARCH_COOLDOWN_MIN", "5.0"))  # Min seconds between searches
SEARCH_COOLDOWN_MAX = float(os.getenv("SEARCH_COOLDOWN_MAX", "12.0"))  # Max seconds between searches
MAX_RETRIES = 3  # Maximum number of retries for failures

def setup_browser(headless=False):
    """Set up and return a Selenium browser instance with anti-scraping measures."""
    # Auto-install chromedriver that matches the Chrome version
    chromedriver_autoinstaller.install()
    
    chrome_options = Options()
    
    # Use headless mode if requested, but visible browsers are better for avoiding detection
    if headless:
        chrome_options.add_argument("--headless")
    
    # Add common options
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Anti-scraping measures
    # Rotate user agents
    user_agent = get_random_user_agent()
    chrome_options.add_argument(f"--user-agent={user_agent}")
    
    # Disable automation flags
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Add some randomization to window size to appear more human-like
    base_width, base_height = 1280, 800
    width_variation = random.randint(-50, 50)
    height_variation = random.randint(-50, 50)
    chrome_options.add_argument(f"--window-size={base_width + width_variation},{base_height + height_variation}")
    
    # Create browser directly
    browser = webdriver.Chrome(options=chrome_options)
    
    # Additional settings after browser is initialized
    browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    logger.info(f"Browser set up with user agent: {user_agent}")
    return browser

def access_movie_page_by_id(browser, imdb_id, retry_count=0):
    """
    Directly access an IMDb movie page using its ID with anti-scraping measures.
    
    Args:
        browser: Selenium browser instance
        imdb_id: IMDb ID of the movie
        retry_count: Current retry attempt
        
    Returns:
        Movie URL if successful, None otherwise
    """
    try:
        movie_url = f"https://www.imdb.com/title/{imdb_id}/"
        
        # Add random delay before navigating
        random_sleep(1, 3)
        
        browser.get(movie_url)
        
        # Add randomized wait time
        wait_time = random.uniform(2, 5)
        WebDriverWait(browser, wait_time).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1[data-testid='hero__pageTitle']"))
        )
        
        # Add some random scroll behavior to look more human
        scroll_amount = random.randint(100, 300)
        browser.execute_script(f"window.scrollTo(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        
        logger.info(f"Successfully accessed IMDb movie page for ID: {imdb_id}")
        return movie_url
    
    except Exception as e:
        # Use exponential backoff for retries
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error accessing IMDb movie page for ID {imdb_id}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return access_movie_page_by_id(browser, imdb_id, retry_count + 1)
        else:
            logger.warning(f"Error accessing IMDb movie page for ID {imdb_id} after {MAX_RETRIES} attempts: {e}")
            return None

def search_movie_on_imdb(browser, title, year=None, retry_count=0):
    """
    Search for a movie on IMDb with anti-scraping measures.
    
    Args:
        browser: Selenium browser instance
        title: Movie title to search for
        year: Movie year (optional)
        retry_count: Current retry attempt
        
    Returns:
        URL of the first search result or None if not found
    """
    try:
        search_query = title
        if year:
            search_query += f" {year}"
            
        logger.info(f"Searching for movie: {search_query}")
        
        # Random delay before navigation
        random_sleep(1, 3)
        
        # Navigate to IMDb
        browser.get("https://www.imdb.com/")
        
        # Wait with randomized delay
        random_sleep(1, 2)
        
        # Find and fill search box with human-like typing
        search_box = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "suggestion-search"))
        )
        search_box.clear()
        
        # Type search query with random delays between characters
        for char in search_query:
            search_box.send_keys(char)
            time.sleep(random.uniform(0.05, 0.2))  # Mimic human typing
        
        # Random pause before submitting search
        random_sleep(0.5, 1.5)
        
        search_box.send_keys(Keys.RETURN)
        
        # Wait for search results with randomized delay
        wait_time = random.uniform(3, 6)
        WebDriverWait(browser, wait_time).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".findList"))
        )
        
        # Add some random scrolling to appear more human-like
        scroll_amount = random.randint(100, 300)
        browser.execute_script(f"window.scrollTo(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        
        # Get first movie result
        first_result = browser.find_element(By.CSS_SELECTOR, ".findResult.odd:first-child a") 
        movie_url = first_result.get_attribute("href")
        
        return movie_url
        
    except Exception as e:
        # Use exponential backoff for retries
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error searching for movie '{title}', retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return search_movie_on_imdb(browser, title, year, retry_count + 1)
        else:
            logger.warning(f"Error searching for movie '{title}' after {MAX_RETRIES} attempts: {e}")
            return None

def rate_movie_on_imdb(browser, movie_url, rating, retry_count=0):
    """
    Rate a movie on IMDb with anti-scraping measures.
    
    Args:
        browser: Selenium browser instance
        movie_url: URL of the movie page
        rating: Rating value (1-10)
        retry_count: Current retry attempt
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Random delay before navigation
        random_sleep(1, 3)
        
        # Navigate to movie page
        browser.get(movie_url)
        
        # Wait for page to load with randomized delay
        wait_time = random.uniform(3, 6)
        WebDriverWait(browser, wait_time).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1[data-testid='hero__pageTitle']"))
        )
        
        # Add human-like scrolling behavior
        scroll_height = browser.execute_script("return document.body.scrollHeight")
        for _ in range(random.randint(2, 4)):  # Random number of scroll actions
            scroll_position = random.randint(100, min(scroll_height - 200, 500))
            browser.execute_script(f"window.scrollTo(0, {scroll_position});")
            time.sleep(random.uniform(0.5, 1.5))  # Random delay between scrolls
        
        # Try to find if there's an existing rating
        try:
            existing_rating = browser.find_element(By.CSS_SELECTOR, "button.ipc-btn--on-accent2")
            logger.info("Movie already has a rating, skipping")
            return True
        except NoSuchElementException:
            # No existing rating, proceed
            pass
        
        # Add random delay before trying to rate
        random_sleep(1, 3)
        
        # Find and click on rating button
        try:
            # First look for the rate button
            rate_button = WebDriverWait(browser, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Rate']"))
            )
            
            # Random pause before clicking
            random_sleep(0.5, 1.5)
            
            rate_button.click()
            
            # Select the rating with random delay
            random_sleep(1, 2)
            
            # IMDb uses a 1-10 scale, and the rating buttons are indexed accordingly
            WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ipc-rating-prompt__rating-buttons"))
            )
            
            # Find the specific rating button
            rating_buttons = browser.find_elements(By.CSS_SELECTOR, ".ipc-rating-prompt__rating-buttons button")
            if rating_buttons and len(rating_buttons) >= rating:
                # Random pause before selecting rating
                random_sleep(0.5, 1.5)
                
                # Click on the button corresponding to the rating (ratings are 1-indexed)
                rating_buttons[rating-1].click()
                
                # Wait for the rating to be submitted with random delay
                random_sleep(1, 3)
                
                logger.info(f"Successfully rated movie with {rating}/10")
                return True
            else:
                logger.warning(f"Could not find rating button for value {rating}")
                return False
                
        except (NoSuchElementException, ElementClickInterceptedException, TimeoutException) as e:
            # Use exponential backoff for retries
            if retry_count < MAX_RETRIES:
                backoff_time = exponential_backoff(retry_count)
                logger.warning(f"Error rating movie, retrying in {backoff_time:.2f}s: {e}")
                time.sleep(backoff_time)
                return rate_movie_on_imdb(browser, movie_url, rating, retry_count + 1)
            else:
                logger.warning(f"Error rating movie after {MAX_RETRIES} attempts: {e}")
                return False
            
    except Exception as e:
        # Use exponential backoff for retries
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error rating movie, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return rate_movie_on_imdb(browser, movie_url, rating, retry_count + 1)
        else:
            logger.warning(f"Error rating movie after {MAX_RETRIES} attempts: {e}")
            return False

def migrate_ratings():
    """Migrate ratings from Douban to IMDb based on the migration plan with anti-scraping measures."""
    # Load migration plan
    migration_plan = load_json(MIGRATION_PLAN_PATH)
    if not migration_plan:
        logger.error("Failed to load migration plan")
        return False
    
    movies_to_migrate = migration_plan.get("to_migrate", [])
    if not movies_to_migrate:
        logger.info("No movies to migrate")
        return True
    
    # Limit the number of movies to migrate in one session
    movies_to_migrate = movies_to_migrate[:MAX_MOVIES_PER_SESSION]
    
    logger.info(f"Preparing to migrate {len(movies_to_migrate)} movies")
    
    # Setup browser (non-headless to better avoid detection)
    browser = None
    results = {
        "successful": [],
        "failed": []
    }
    
    try:
        browser = setup_browser(headless=False)
        login_to_imdb(browser)
        
        # Add a significant delay after login before starting
        random_sleep(5, 10)
        
        # Add randomization to the order of movies to migrate
        # This helps avoid detection by not always processing in the same order
        if len(movies_to_migrate) > 3:  # Only randomize if we have enough movies
            random.shuffle(movies_to_migrate)
        
        # Process each movie
        for idx, movie in enumerate(tqdm(movies_to_migrate, desc="Migrating ratings")):
            try:
                # Add a longer break every few movies
                if idx > 0 and idx % 5 == 0:
                    break_time = random.uniform(15, 30)
                    logger.info(f"Taking a longer break of {break_time:.1f}s after {idx} movies")
                    time.sleep(break_time)
                
                title = movie["douban"]["title"]
                year = movie["douban"].get("year")
                imdb_id = movie["douban"].get("imdb_id")
                imdb_rating = movie.get("imdb_equivalent")
                
                if not imdb_rating:
                    logger.warning(f"No IMDb equivalent rating for {title}, skipping")
                    results["failed"].append({
                        "movie": movie,
                        "reason": "No IMDb equivalent rating"
                    })
                    continue
                
                # Get movie page URL - try direct access by ID first if available
                movie_url = None
                if imdb_id:
                    logger.info(f"Using direct IMDb ID for {title}: {imdb_id}")
                    movie_url = access_movie_page_by_id(browser, imdb_id)
                
                # If direct access failed or no IMDb ID, fall back to search
                if not movie_url:
                    logger.info(f"Searching for {title} on IMDb")
                    movie_url = search_movie_on_imdb(browser, title, year)
                
                if not movie_url:
                    logger.warning(f"Could not find movie {title} on IMDb")
                    results["failed"].append({
                        "movie": movie,
                        "reason": "Movie not found on IMDb"
                    })
                    # Use a longer cooldown after a failed search
                    random_sleep(SEARCH_COOLDOWN_MIN, SEARCH_COOLDOWN_MAX)
                    continue
                
                # Add random delay before rating
                random_sleep(COOLDOWN_MIN, COOLDOWN_MAX)
                
                # Rate the movie
                success = rate_movie_on_imdb(browser, movie_url, imdb_rating)
                if success:
                    results["successful"].append({
                        "movie": movie,
                        "imdb_url": movie_url,
                        "rating": imdb_rating
                    })
                else:
                    results["failed"].append({
                        "movie": movie,
                        "imdb_url": movie_url,
                        "reason": "Failed to rate movie"
                    })
                
                # Variable cooldown between ratings to avoid detection
                cooldown = random.uniform(COOLDOWN_MIN, COOLDOWN_MAX)
                logger.info(f"Waiting {cooldown:.1f}s before next rating")
                time.sleep(cooldown)
                
            except Exception as e:
                logger.error(f"Error processing movie {movie['douban']['title']}: {e}")
                results["failed"].append({
                    "movie": movie,
                    "reason": f"Exception: {str(e)}"
                })
                
                # Use a longer cooldown after an error
                random_sleep(COOLDOWN_MAX, COOLDOWN_MAX * 2)
        
        # Save results
        save_json(results, MIGRATION_RESULTS_PATH)
        
        # Print summary
        logger.info(f"Migration completed:")
        logger.info(f"  Successful: {len(results['successful'])}")
        logger.info(f"  Failed: {len(results['failed'])}")
        logger.info(f"Results saved to {MIGRATION_RESULTS_PATH}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False
        
    finally:
        if browser:
            browser.quit()

if __name__ == "__main__":
    if migrate_ratings():
        print("Migration completed successfully")
    else:
        print("Migration failed. Check the log for details.") 