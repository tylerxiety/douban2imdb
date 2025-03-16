"""
Script to migrate ratings from Douban to IMDb.
"""
import os
import time
import json
import logging
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import chromedriver_autoinstaller
from tqdm import tqdm
from dotenv import load_dotenv

from utils import ensure_data_dir, load_json, save_json, logger, random_sleep, exponential_backoff

# Load environment variables
load_dotenv()

# Paths
DOUBAN_EXPORT_PATH = os.getenv("DOUBAN_EXPORT_PATH", "data/douban_ratings.json")
IMDB_EXPORT_PATH = os.getenv("IMDB_EXPORT_PATH", "data/imdb_ratings.json")
MIGRATION_PLAN_PATH = os.getenv("MIGRATION_PLAN_PATH", "data/migration_plan.json")

# Constants
MAX_RETRIES = 3

def setup_browser():
    """Set up and return a Selenium browser instance."""
    # Auto-install chromedriver that matches the Chrome version
    chromedriver_autoinstaller.install()
    
    chrome_options = Options()
    
    # Add common options
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Create browser directly
    browser = webdriver.Chrome(options=chrome_options)
    
    logger.info("Browser set up")
    return browser

def login_to_imdb_manually(browser):
    """Navigate to IMDb and assist with manual login."""
    try:
        # Navigate to IMDb login page
        browser.get("https://www.imdb.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.imdb.com%2Fregistration%2Fap-signin-handler%2Fimdb_us&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=imdb_us&openid.mode=checkid_setup&siteState=eyJvcGVuaWQuYXNzb2NfaGFuZGxlIjoiaW1kYl91cyIsInJlZGlyZWN0VG8iOiJodHRwczovL3d3dy5pbWRiLmNvbS8_cmVmXz1sb2dpbiJ9&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
        
        print("\n=== MANUAL LOGIN REQUIRED ===")
        print("1. A browser window has opened to the IMDb login page")
        print("2. Please log in manually with your IMDb/Amazon credentials")
        print("3. Make sure you're fully logged in before continuing")
        
        input("\nPress Enter AFTER you have successfully logged in to IMDb...")
        
        # Verify login
        try:
            user_menu = browser.find_element(By.ID, "navUserMenu")
            logger.info("Login successful (found user menu)")
            return True
        except NoSuchElementException:
            # Ask user to confirm login status
            confirmation = input("Are you successfully logged in to IMDb? (y/n): ")
            return confirmation.lower() in ['y', 'yes']
            
    except Exception as e:
        logger.error(f"Error during login: {e}")
        return False

def create_migration_plan():
    """Create a migration plan based on exported ratings."""
    ensure_data_dir()
    
    # Check if Douban ratings file exists
    if not os.path.exists(DOUBAN_EXPORT_PATH):
        print(f"Error: Douban ratings file not found at {DOUBAN_EXPORT_PATH}")
        print("Please run src/douban_export.py first.")
        return False
    
    # Load Douban ratings
    douban_ratings = load_json(DOUBAN_EXPORT_PATH)
    print(f"Loaded {len(douban_ratings)} ratings from Douban export")
    
    # Check if IMDb export exists and load it
    imdb_ratings = []
    existing_imdb_ids = set()
    if os.path.exists(IMDB_EXPORT_PATH):
        imdb_ratings = load_json(IMDB_EXPORT_PATH)
        print(f"Loaded {len(imdb_ratings)} ratings from IMDb export")
        # Create a set of existing IMDb IDs for quick lookup
        existing_imdb_ids = set(rating.get("imdb_id") for rating in imdb_ratings if rating.get("imdb_id"))
    
    # Create migration plan
    migration_plan = []
    
    for douban_rating in douban_ratings:
        imdb_id = douban_rating.get("imdb_id")
        if not imdb_id:
            print(f"No IMDb ID found for: {douban_rating.get('title')}")
            continue
        
        # Skip already rated movies
        if imdb_id in existing_imdb_ids:
            print(f"Movie already rated on IMDb: {douban_rating.get('title')}")
            continue
        
        # Convert Douban rating (1-5) to IMDb rating (1-10)
        # Douban ratings are 1-5 stars, IMDb is 1-10 stars
        douban_score = douban_rating.get("rating")
        if douban_score is None:
            continue
        
        # Map Douban score to IMDb scale
        imdb_score = 2 * douban_score
        
        # Add to migration plan
        migration_plan.append({
            "title": douban_rating.get("title"),
            "year": douban_rating.get("year"),
            "imdb_id": imdb_id,
            "douban_rating": douban_score,
            "imdb_rating": imdb_score
        })
    
    print(f"Created migration plan with {len(migration_plan)} movies to rate on IMDb")
    
    # Save migration plan
    save_json(migration_plan, MIGRATION_PLAN_PATH)
    print(f"Migration plan saved to {MIGRATION_PLAN_PATH}")
    
    return True

def access_movie_page_by_id(browser, imdb_id, retry_count=0):
    """Navigate to a movie page by IMDb ID with retry logic."""
    try:
        url = f"https://www.imdb.com/title/{imdb_id}/"
        browser.get(url)
        
        # Wait for the page to load
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".title-overview"))
        )
        
        # Random scroll to mimic human behavior
        browser.execute_script(f"window.scrollBy(0, {random.randint(100, 300)});")
        time.sleep(random.uniform(0.5, 1.5))
        
        return True
        
    except Exception as e:
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error accessing movie page {imdb_id}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return access_movie_page_by_id(browser, imdb_id, retry_count + 1)
        else:
            logger.error(f"Failed to access movie page {imdb_id} after {MAX_RETRIES} attempts: {e}")
            return False

def rate_movie_on_imdb(browser, imdb_id, rating, title=None, retry_count=0):
    """Rate a movie on IMDb with retry logic and user assistance when needed."""
    try:
        # First access the movie page
        if not access_movie_page_by_id(browser, imdb_id):
            return False
        
        title_text = title or browser.title.split(" - IMDb")[0]
        print(f"\nRating {title_text} ({imdb_id}) as {rating}/10")
        
        # Try to locate the rate button
        try:
            # Check if movie is already rated
            already_rated_elems = browser.find_elements(By.CSS_SELECTOR, ".user-rating")
            if already_rated_elems:
                print(f"Movie {title_text} appears to be already rated, skipping")
                return True
            
            # Locate and click the rate button
            print("Looking for rate button...")
            rate_button_selectors = [
                ".star-rating-button button",
                ".star-rating-widget button",
                "button[data-testid='hero-rating-bar__user-rating']"
            ]
            
            rate_button = None
            for selector in rate_button_selectors:
                try:
                    rate_elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if rate_elements:
                        rate_button = rate_elements[0]
                        break
                except Exception as e:
                    print(f"Error with selector {selector}: {e}")
            
            if rate_button:
                print("Found rate button, clicking...")
                rate_button.click()
                time.sleep(1)
            else:
                print("Rate button not found. Here are two ways to proceed:")
                print("1. Try to rate manually by clicking on the stars")
                print("2. Skip this movie")
                choice = input("Enter 1 to try manual rating, any other key to skip: ")
                if choice == "1":
                    print("Please rate the movie manually. ")
                    input("Press Enter when you've completed rating or want to skip...")
                    print("Continuing to next movie...")
                    return True
                else:
                    print("Skipping this movie...")
                    return False
            
            # Select the rating from the popup
            print("Looking for rating stars...")
            time.sleep(1)
            
            # Different sites have different rating UIs, try multiple selectors
            rating_selectors = [
                f"button[aria-label='{rating} stars']",
                f"button[aria-label='Rate {rating}']",
                f".star-rating-stars a[title='Click to rate: {rating}']"
            ]
            
            rating_element = None
            for selector in rating_selectors:
                try:
                    elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        rating_element = elements[0]
                        break
                except Exception as e:
                    print(f"Error with rating selector {selector}: {e}")
            
            if rating_element:
                print(f"Found rating element for {rating} stars, clicking...")
                rating_element.click()
                time.sleep(1)
                
                # Check for confirmation
                confirmation_selectors = [
                    ".ipl-rating-interactive__star-rating",
                    ".user-rating",
                    ".imdb-rating .star-rating-text"
                ]
                
                confirmation_found = False
                for selector in confirmation_selectors:
                    elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        print("Rating confirmation found")
                        confirmation_found = True
                        break
                
                if not confirmation_found:
                    print("No explicit rating confirmation found")
                    input("Press Enter if the rating was successful, or type 'retry' to try again: ")
                
                return True
                
            else:
                print("Rating selection not found. Please try rating manually.")
                input("Press Enter after manual rating or to skip this movie...")
                return True
                
        except (NoSuchElementException, StaleElementReferenceException) as e:
            print(f"Error finding rating elements: {e}")
            print("Please try rating manually.")
            input("Press Enter after manual rating or to skip this movie...")
            return True
            
    except Exception as e:
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error rating movie {imdb_id}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count + 1)
        else:
            logger.error(f"Failed to rate movie {imdb_id} after {MAX_RETRIES} attempts: {e}")
            print("Manual intervention required for this movie.")
            choice = input("Press Enter to skip or type 'retry' to try once more: ")
            if choice.lower() == "retry":
                return rate_movie_on_imdb(browser, imdb_id, rating, title, 0)
            return False

def execute_migration():
    """Execute the migration plan with manual assistance."""
    if not os.path.exists(MIGRATION_PLAN_PATH):
        print(f"Migration plan not found: {MIGRATION_PLAN_PATH}")
        print("Please run create_migration_plan() first.")
        return False
    
    # Load migration plan
    migration_plan = load_json(MIGRATION_PLAN_PATH)
    
    print(f"\n===== EXECUTING MIGRATION PLAN =====")
    print(f"Found {len(migration_plan)} movies to rate on IMDb")
    print("The script will assist you in rating these movies on IMDb.")
    print("For each movie, the script will:")
    print("1. Navigate to the movie page")
    print("2. Attempt to rate it automatically")
    print("3. Prompt for manual assistance if needed")
    
    max_movies = int(input("\nEnter maximum number of movies to process in this session (or press Enter for all): ") or len(migration_plan))
    
    confirmation = input(f"\nReady to start rating up to {max_movies} movies? (y/n): ")
    if confirmation.lower() not in ['y', 'yes']:
        print("Migration cancelled.")
        return False
    
    browser = None
    try:
        # Setup browser
        browser = setup_browser()
        
        # Login to IMDb
        if not login_to_imdb_manually(browser):
            print("Login failed or was not confirmed. Exiting.")
            return False
        
        # Process movies
        success_count = 0
        failure_count = 0
        
        for i, movie in enumerate(migration_plan[:max_movies]):
            print(f"\n--- Movie {i+1}/{min(max_movies, len(migration_plan))} ---")
            print(f"Title: {movie.get('title')} ({movie.get('year')})")
            print(f"IMDb ID: {movie.get('imdb_id')}")
            print(f"Rating: Douban {movie.get('douban_rating')}/5 → IMDb {movie.get('imdb_rating')}/10")
            
            # Prompt user before each movie
            if i > 0 and i % 5 == 0:
                cont = input("Press Enter to continue, or type 'break' to stop: ")
                if cont.lower() == 'break':
                    print("Pausing migration as requested.")
                    break
            
            # Rate the movie
            success = rate_movie_on_imdb(
                browser, 
                movie.get('imdb_id'), 
                movie.get('imdb_rating'), 
                movie.get('title')
            )
            
            if success:
                success_count += 1
                print(f"Successfully rated: {movie.get('title')}")
            else:
                failure_count += 1
                print(f"Failed to rate: {movie.get('title')}")
            
            # Add random delay between ratings
            if i < min(max_movies, len(migration_plan)) - 1:
                delay = random.uniform(2, 5)
                print(f"Waiting {delay:.1f} seconds before next movie...")
                time.sleep(delay)
        
        print("\n=== MIGRATION SUMMARY ===")
        print(f"Total movies processed: {success_count + failure_count}")
        print(f"Successfully rated: {success_count}")
        print(f"Failed to rate: {failure_count}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        print(f"Error: {str(e)}")
        return False
        
    finally:
        if browser:
            browser.quit()

def migrate_ratings():
    """Main function to guide the user through the migration process."""
    ensure_data_dir()
    
    print("\n===== DOUBAN TO IMDB RATING MIGRATION =====")
    print("This script will guide you through migrating your Douban ratings to IMDb.")
    print("You can create a migration plan first, then execute it to rate movies on IMDb.")
    print("\nBefore continuing, make sure you have:")
    print("1. Exported your Douban ratings (run src/douban_export.py)")
    print("2. Optional: Run src/imdb_export.py to export existing IMDb ratings")
    
    while True:
        print("\nChoose an action:")
        print("1. Create migration plan")
        print("2. Execute migration plan")
        print("3. Create and execute migration plan")
        print("4. Exit")
        
        choice = input("\nEnter your choice (1-4): ")
        
        if choice == "1":
            create_migration_plan()
        elif choice == "2":
            execute_migration()
        elif choice == "3":
            if create_migration_plan():
                execute_migration()
        elif choice == "4":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please enter 1-4.")

if __name__ == "__main__":
    migrate_ratings() 