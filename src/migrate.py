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
import argparse

from utils import ensure_data_dir, load_json, save_json, logger, random_sleep, exponential_backoff, get_random_user_agent

# Load environment variables
load_dotenv()

# Paths
DOUBAN_EXPORT_PATH = os.getenv("DOUBAN_EXPORT_PATH", "data/douban_ratings.json")
IMDB_EXPORT_PATH = os.getenv("IMDB_EXPORT_PATH", "data/imdb_ratings.json")
MIGRATION_PLAN_PATH = os.getenv("MIGRATION_PLAN_PATH", "data/migration_plan.json")
MIGRATION_PROGRESS_PATH = os.getenv("MIGRATION_PROGRESS_PATH", "data/migration_progress.json")

# Constants
MAX_RETRIES = 5  # Increased from 3 to 5 for better retry handling
SPEED_MODE = True  # Set to True to disable images for faster loading
CONNECTION_TIMEOUT = 90  # Seconds to wait for connections before timeout
WAIT_BETWEEN_MOVIES = (0.5, 1)  # Further reduced wait between movies for faster processing
PROXY = os.getenv("PROXY", None)  # Proxy in format http://user:pass@host:port

def setup_browser(headless=False, proxy=None):
    """Set up and return a browser for automation."""
    try:
        logger.info("Setting up browser for IMDb interaction")
        
        # Install chromedriver that matches Chrome version
        try:
            chromedriver_autoinstaller.install()
        except Exception as e:
            logger.warning(f"Failed to install chromedriver normally: {e}. Trying no_ssl mode.")
            chromedriver_autoinstaller.install(no_ssl=True)
        
        # Browser options
        options = webdriver.ChromeOptions()
        
        # Set user agent to appear more like a regular browser
        user_agent = get_random_user_agent()
        logger.info(f"Using user agent: {user_agent}")
        options.add_argument(f'user-agent={user_agent}')
        
        # Add proxy if specified
        if proxy:
            logger.info(f"Using proxy: {proxy}")
            options.add_argument(f'--proxy-server={proxy}')
        
        # Improve anti-detection measures
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Set language to English
        options.add_argument("--lang=en-US")
        
        # Additional performance options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--dns-prefetch-disable")
        
        # Handle connection issues
        options.add_argument("--disable-features=NetworkService")
        options.add_argument("--disable-web-security")
        options.add_argument("--ignore-certificate-errors")
        
        # Disable images for faster loading if in speed mode
        if SPEED_MODE:
            prefs = {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values.notifications": 2,
                # Disable videos, plugins, and other resource-heavy elements
                "profile.managed_default_content_settings.plugins": 2,
                "profile.managed_default_content_settings.media_stream": 2,
                "profile.managed_default_content_settings.geolocation": 2,
                "profile.managed_default_content_settings.popups": 2,
                "profile.managed_default_content_settings.javascript": 1,  # Keep JavaScript enabled for functionality
                "profile.managed_default_content_settings.cookies": 1,  # Keep cookies enabled for login
                "profile.managed_default_content_settings.automatic_downloads": 2
            }
            options.add_experimental_option("prefs", prefs)
            
            # Additional performance options
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("--disable-plugins-discovery")
            options.add_argument("--disable-infobars")
        
        # Headless mode if requested
        if headless:
            options.add_argument("--headless=new")
        
        # Initialize browser with custom options
        browser = webdriver.Chrome(options=options)
        
        # Set reasonable page load timeout
        browser.set_page_load_timeout(CONNECTION_TIMEOUT)  # Use the global timeout setting
        
        # Set window size to typical desktop size to avoid mobile views
        browser.set_window_size(1366, 768)
        
        # Execute JS to modify navigator properties to make automation less detectable
        browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Add a random scroll behavior and delay to mimic human interaction
        browser.execute_script("window.scrollTo(0, document.body.scrollHeight/5)")
        time.sleep(random.uniform(1, 2))
        
        logger.info("Browser setup successful")
        return browser
    except Exception as e:
        logger.error(f"Error setting up browser: {e}")
        raise

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
    """Create a migration plan by invoking the prepare_migration module."""
    try:
        # Import prepare_migration here to avoid circular imports
        from prepare_migration import prepare_migration_plan
        
        logger.info("Creating migration plan...")
        migration_plan = prepare_migration_plan()
        
        if migration_plan and isinstance(migration_plan, dict):
            # Success - provide stats
            to_migrate = len(migration_plan.get("to_migrate", []))
            already_rated = len(migration_plan.get("already_rated", []))
            total = to_migrate + already_rated
            
            print(f"\nMigration plan created successfully!")
            print(f"Total movies: {total}")
            print(f"To migrate: {to_migrate} ({(to_migrate/total*100 if total > 0 else 0):.1f}%)")
            print(f"Already rated on IMDb: {already_rated} ({(already_rated/total*100 if total > 0 else 0):.1f}%)")
            
            if "stats" in migration_plan:
                stats = migration_plan["stats"]
                print("\nMatching statistics:")
                print(f"Matched by IMDb ID: {stats.get('matched_by_id', 0)}")
                print(f"Matched by title similarity: {stats.get('matched_by_title', 0)}")
                print(f"Not matched: {stats.get('not_matched', 0)}")
                print(f"TV shows combined: {stats.get('tv_shows_combined', 0)}")
            
            print(f"\nMigration plan saved to {MIGRATION_PLAN_PATH}")
            return True
        else:
            logger.error("Failed to create migration plan")
            return False
    except Exception as e:
        logger.error(f"Error creating migration plan: {e}")
        return False

def access_movie_page_by_id(browser, imdb_id, retry_count=0):
    """Navigate to a movie page by IMDb ID with retry logic."""
    try:
        # Ensure we have the main show ID, not episode-specific
        main_imdb_id = imdb_id.split('/')[0] if '/' in imdb_id else imdb_id
        url = f"https://www.imdb.com/title/{main_imdb_id}/"
        
        logger.info(f"Accessing URL: {url}")
        
        # Add a random delay before access to mimic human behavior
        time.sleep(random.uniform(0.1, 0.3))
        
        # Try to handle connection timeouts gracefully
        try:
            browser.get(url)
        except TimeoutException:
            logger.warning(f"Timeout when accessing {url}, trying with a longer timeout")
            browser.set_page_load_timeout(CONNECTION_TIMEOUT * 2)  # Double the timeout for retry
            browser.get(url)
        
        # Wait for the page to load with a longer timeout
        try:
            WebDriverWait(browser, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.sc-69e49b85-0, .title-overview, .TitleBlock__Container"))
            )
        except TimeoutException:
            logger.warning("Page structure elements not found. Trying alternative elements")
            # Try alternative elements that might indicate page is loaded
            try:
                WebDriverWait(browser, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .ipc-page-content-container, body"))
                )
                logger.info("Found alternative page elements")
            except:
                logger.warning("Alternative elements also not found, continuing anyway")
        
        # Check if we're on the correct page
        current_url = browser.current_url
        if '/episodes?season=' in current_url or '/episodes/' in current_url:
            # We're on an episodes page, navigate to main show page
            logger.warning(f"Landed on episodes page: {current_url}, redirecting to main show page")
            main_show_url = f"https://www.imdb.com/title/{main_imdb_id}/"
            browser.get(main_show_url)
            time.sleep(3)  # Give more time to load
        
        # Wait for key elements with a longer timeout
        try:
            WebDriverWait(browser, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .title-overview h1, .TitleHeader__TitleText"))
            )
        except:
            logger.warning("Couldn't find title element, but proceeding anyway")
        
        # Perform random scrolls to mimic human behavior
        scroll_amount = random.randint(100, 400)
        browser.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        
        # Scroll back up a bit
        browser.execute_script(f"window.scrollBy(0, -{random.randint(50, 200)});")
        time.sleep(random.uniform(0.3, 1.0))
        
        return True
        
    except Exception as e:
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error accessing page {imdb_id}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            # Reset browser page load timeout to default before retry
            try:
                browser.set_page_load_timeout(CONNECTION_TIMEOUT)
            except:
                pass
            return access_movie_page_by_id(browser, imdb_id, retry_count + 1)
        else:
            logger.error(f"Failed to access page {imdb_id} after {MAX_RETRIES} attempts: {e}")
            return False

def highlight_element(browser, element, color="red", border=2):
    """Highlight an element for easier identification."""
    original_style = element.get_attribute("style")
    style = f"border: {border}px solid {color}; background: yellow;"
    browser.execute_script(f"arguments[0].setAttribute('style', '{style}');", element)
    return original_style

def highlight_potential_rating_elements(browser, rating):
    """Highlight all potential rating elements on the page."""
    print("Highlighting potential rating elements...")
    highlighted_elements = []
    
    # Define selectors that might contain rating stars
    potential_selectors = [
        "button", 
        "[class*='rating']", 
        "[class*='star']",
        "[aria-label*='Rate']",
        "[data-testid*='rating']",
        "li"
    ]
    
    for selector in potential_selectors:
        elements = browser.find_elements(By.CSS_SELECTOR, selector)
        for element in elements:
            try:
                # Skip elements that are too large (likely containers)
                size = element.size
                if size['width'] > 200 or size['height'] > 200:
                    continue
                
                # Check if the element or its children might be clickable
                is_displayed = element.is_displayed()
                if not is_displayed:
                    continue
                
                # Check if the element has any text or attribute that might indicate it's a rating star
                element_text = element.text.strip()
                element_html = element.get_attribute('outerHTML')
                
                # Look for indicators that this might be a rating element
                rating_indicators = [
                    f"rate-{rating}", f"rating-{rating}", f"Rate {rating}", f"{rating} stars",
                    "star", "rating", "rate"
                ]
                
                is_potential_rating = any(indicator.lower() in element_html.lower() for indicator in rating_indicators)
                
                if is_potential_rating:
                    original_style = highlight_element(browser, element)
                    highlighted_elements.append((element, original_style))
                    print(f"Highlighted element: {element_html[:100]}...")
            except:
                pass
    
    print(f"Highlighted {len(highlighted_elements)} potential rating elements")
    return highlighted_elements

def rate_movie_on_imdb(browser, imdb_id, rating, title="", retry_count=0, max_retries=3):
    """Rate a movie on IMDb with up to 3 retry attempts."""
    try:
        # Access the movie page
        if not access_movie_page_by_id(browser, imdb_id):
            logger.error(f"Could not access movie page for {imdb_id}")
            return False
        
        # Wait for the page to load
        try:
            WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1[data-testid='hero__pageTitle']"))
            )
        except:
            logger.warning(f"Title element not found for {imdb_id}, but continuing anyway")
        
        # Get the movie title from the page if available
        try:
            page_title = browser.find_element(By.CSS_SELECTOR, "h1[data-testid='hero__pageTitle']").text
            logger.info(f"Found movie: {page_title}")
        except:
            page_title = title
            logger.warning(f"Could not get title from page, using provided title: {title}")
        
        # Find and click the rate button
        try:
            # Try to find the rate button
            rate_button = None
            
            # First try the "Rate" button if not already rated
            try:
                rate_button = browser.find_element(By.CSS_SELECTOR, "button[data-testid='hero-rating-bar__rate-button']")
            except:
                pass
            
            # If not found, try to find the "Your Rating" element (already rated)
            if not rate_button:
                try:
                    your_rating = browser.find_element(By.CSS_SELECTOR, "div[data-testid='hero-rating-bar__user-rating']")
                    logger.info(f"Movie {imdb_id} ({page_title}) is already rated")
                    
                    # Skip already rated movies without asking
                    logger.info(f"Skipping already rated movie: {page_title}")
                    return True
                except:
                    logger.warning("Could not find rate button or existing rating")
                    return False
            else:
                # Click the rate button
                rate_button.click()
        except Exception as e:
            logger.error(f"Error finding or clicking rate button: {e}")
            return False
        
        # Wait for the rating popup
        try:
            WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='starbar']"))
            )
        except:
            logger.error("Rating popup did not appear")
            return False
        
        # Find and click the appropriate star
        try:
            # Convert rating to an integer between 1-10
            rating_int = int(float(rating))
            if rating_int < 1:
                rating_int = 1
            elif rating_int > 10:
                rating_int = 10
            
            # Find all star elements
            stars = browser.find_elements(By.CSS_SELECTOR, "button[data-testid^='starbar-rating-']")
            
            if not stars or len(stars) < 10:
                logger.error(f"Could not find rating stars (found {len(stars) if stars else 0})")
                return False
            
            # Click the appropriate star (stars are 1-indexed)
            stars[rating_int - 1].click()
            logger.info(f"Selected rating {rating_int} for {page_title}")
            
            # Wait for rating to be submitted
            time.sleep(1)
            
            # Look for confirmation
            confirmation_found = False
            try:
                # Wait for the "Your rating" text to appear
                WebDriverWait(browser, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Your rating')]"))
                )
                confirmation_found = True
            except:
                logger.warning("No explicit rating confirmation found")
            
            # If no confirmation, retry up to max_retries times
            if not confirmation_found:
                if retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"No explicit rating confirmation found, automatically retrying... (Attempt {retry_count} of {max_retries})")
                    
                    # Close any open dialogs
                    try:
                        browser.find_element(By.CSS_SELECTOR, "button[data-testid='close-button']").click()
                    except:
                        pass
                    
                    # Wait a moment before retrying
                    time.sleep(2)
                    
                    # Try again recursively
                    return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count, max_retries)
                else:
                    logger.warning(f"No confirmation after {max_retries} attempts, assuming rating was successful")
            
            return True
            
        except Exception as e:
            logger.error(f"Error selecting rating: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Error rating movie {imdb_id}: {e}")
        return False

def execute_migration_plan(migration_plan, max_movies=None, test_mode=False):
    """Execute the migration plan and rate movies on IMDb."""
    try:
        # Extract movies to migrate
        movies_to_migrate = migration_plan.get("to_migrate", [])
        total_movies = len(movies_to_migrate)
        
        if not movies_to_migrate:
            logger.warning("No movies to migrate in the plan")
            return False
        
        logger.info(f"Found {total_movies} movies to migrate")
        
        # Apply max_movies limit if specified
        if max_movies and max_movies > 0 and max_movies < total_movies:
            logger.info(f"Limiting to {max_movies} movies as requested")
            movies_to_migrate = movies_to_migrate[:max_movies]
        
        # Load progress data if it exists
        progress_data = {}
        if os.path.exists(MIGRATION_PROGRESS_PATH):
            try:
                with open(MIGRATION_PROGRESS_PATH, 'r', encoding='utf-8') as f:
                    progress_data = json.load(f)
                    logger.info(f"Loaded progress data from {MIGRATION_PROGRESS_PATH}")
                    
                    # Filter out already processed movies using the nested structure for IMDb ID
                    processed_imdb_ids = set(progress_data.get("processed_imdb_ids", []))
                    if processed_imdb_ids:
                        original_count = len(movies_to_migrate)
                        movies_to_migrate = [m for m in movies_to_migrate if (m.get("imdb", {}).get("imdb_id") or m.get("douban", {}).get("imdb_id")) not in processed_imdb_ids]
                        skipped_count = original_count - len(movies_to_migrate)
                        logger.info(f"Skipping {skipped_count} already processed movies")
                        print(f"Skipping {skipped_count} already processed movies from previous batches")
            except Exception as e:
                logger.warning(f"Error loading progress data: {e}")
                progress_data = {"processed_imdb_ids": []}
        else:
            progress_data = {"processed_imdb_ids": []}
        
        # Setup browser once for the entire migration process
        browser = None
        
        try:
            # Setup browser once for the entire migration process
            browser = setup_browser(headless=False, proxy=PROXY)
            
            # Login once at the beginning
            if not login_to_imdb_manually(browser):
                logger.error("Failed to login to IMDb")
                return False
            
            # Process all movies in a single session
            try:
                # Use tqdm for a progress bar
                success_count = 0
                failure_count = 0
                processed_count = 0
                
                for movie in tqdm(movies_to_migrate, desc="Rating movies"):
                    processed_count += 1
                    # Extract movie data from the migration plan structure
                    douban_movie = movie.get("douban", {})
                    imdb_movie = movie.get("imdb", {})
                    
                    # Get the IMDb ID from the IMDb data or Douban data
                    imdb_id = imdb_movie.get("imdb_id") or douban_movie.get("imdb_id")
                    
                    # Get the rating to apply (already converted to IMDb scale)
                    rating_to_apply = movie.get("imdb_rating", 0)
                    
                    # Get the title from Douban data
                    title = douban_movie.get("title", "Unknown")
                    
                    if not imdb_id or not rating_to_apply:
                        logger.warning(f"Missing IMDb ID or rating for movie: {title}")
                        failure_count += 1
                        continue
                    
                    logger.info(f"Processing movie: {title} (IMDb: {imdb_id}, Rating: {rating_to_apply})")
                    
                    try:
                        success = rate_movie_on_imdb(
                            browser, 
                            imdb_id, 
                            rating_to_apply, 
                            title=title, 
                            retry_count=0, 
                            max_retries=3
                        )
                        
                        if success:
                            success_count += 1
                            # Add to processed list
                            if imdb_id not in progress_data["processed_imdb_ids"]:
                                progress_data["processed_imdb_ids"].append(imdb_id)
                                
                                # Save progress after each successful rating
                                try:
                                    with open(MIGRATION_PROGRESS_PATH, 'w', encoding='utf-8') as f:
                                        json.dump(progress_data, f, ensure_ascii=False, indent=2)
                                        f.flush()
                                        os.fsync(f.fileno())
                                        logger.info(f"Updated progress file with {len(progress_data['processed_imdb_ids'])} processed movies")
                                except Exception as e:
                                    logger.warning(f"Error saving progress data: {e}")
                        else:
                            logger.error(f"Failed to rate movie {title}")
                            failure_count += 1
                        
                        # Random wait between movies to avoid detection
                        wait_time = random.uniform(WAIT_BETWEEN_MOVIES[0], WAIT_BETWEEN_MOVIES[1])
                        logger.info(f"Waiting {wait_time:.1f} seconds before next movie...")
                        time.sleep(wait_time)
                        
                    except Exception as e:
                        logger.error(f"Error processing movie {title}: {e}")
                        failure_count += 1
            
            except Exception as e:
                logger.error(f"Error during movie processing: {e}")
        except Exception as e:
            logger.error(f"Error during browser session: {e}")
         
        # Print summary
        print("\n=== Migration Summary ===")
        print(f"Total processed: {processed_count}")
        print(f"Successfully rated: {success_count}")
        print(f"Failed to rate: {failure_count}")
        print(f"Total rated so far: {len(progress_data['processed_imdb_ids'])}")
        print(f"Remaining to rate: {total_movies - len(progress_data['processed_imdb_ids'])}")
        
        return len(progress_data['processed_imdb_ids']) > 0
    
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False
    finally:
        # Always close the browser
        if browser:
            try:
                browser.quit()
            except:
                pass

def migrate_ratings():
    """Interactive function to migrate ratings."""
    print("\n=== Douban to IMDb Rating Migration ===")
    
    # Create data directory if it doesn't exist
    ensure_data_dir()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/migration.log"),
            logging.StreamHandler()
        ]
    )
    
    while True:
        print("\nOptions:")
        print("1. Create migration plan")
        print("2. Execute migration plan")
        print("3. Create plan and execute immediately")
        print("4. Test migration (with debug info)")
        print("5. Reset batch progress")
        print("6. View migration progress")
        print("7. Exit")
        
        choice = input("\nEnter your choice (1-7): ")
        
        if choice == "1":
            create_migration_plan()
        elif choice == "2":
            # Load migration plan
            logger.info(f"Loading migration plan from {MIGRATION_PLAN_PATH}")
            migration_plan = load_json(MIGRATION_PLAN_PATH)
            if migration_plan:
                max_movies = input("Enter maximum number of movies to process (press Enter for all): ")
                max_movies = int(max_movies) if max_movies.strip() else None
                
                test_mode_input = input("Run in test mode with debugging? (y/n): ")
                test_mode = test_mode_input.lower() == "y"
                
                execute_migration_plan(migration_plan, max_movies=max_movies, test_mode=test_mode)
            else:
                print("Failed to load migration plan. Please create one first.")
        elif choice == "3":
            if create_migration_plan():
                # Load the migration plan
                logger.info(f"Loading migration plan from {MIGRATION_PLAN_PATH}")
                migration_plan = load_json(MIGRATION_PLAN_PATH)
                if migration_plan:
                    max_movies = input("Enter maximum number of movies to process (press Enter for all): ")
                    max_movies = int(max_movies) if max_movies.strip() else None
                    
                    test_mode_input = input("Run in test mode with debugging? (y/n): ")
                    test_mode = test_mode_input.lower() == "y"
                    
                    execute_migration_plan(migration_plan, max_movies=max_movies, test_mode=test_mode)
        elif choice == "4":
            # Test mode
            logger.info(f"Loading migration plan from {MIGRATION_PLAN_PATH}")
            migration_plan = load_json(MIGRATION_PLAN_PATH)
            if migration_plan:
                max_movies = input("Enter maximum number of movies to test (recommended: 1-3): ")
                max_movies = int(max_movies) if max_movies.strip() else 1
                
                execute_migration_plan(migration_plan, max_movies=max_movies, test_mode=True)
            else:
                print("Failed to load migration plan. Please create one first.")
        elif choice == "5":
            # Reset batch progress
            confirmation = input("Are you sure you want to reset all batch progress? This will clear the record of which movies have been processed. (y/n): ")
            if confirmation.lower() == "y":
                if os.path.exists(MIGRATION_PROGRESS_PATH):
                    os.remove(MIGRATION_PROGRESS_PATH)
                    print("Batch progress has been reset. Next run will start from the beginning.")
                else:
                    print("No progress file found.")
            else:
                print("Reset cancelled.")
        elif choice == "6":
            # View migration progress
            if os.path.exists(MIGRATION_PROGRESS_PATH):
                progress_data = load_json(MIGRATION_PROGRESS_PATH)
                if progress_data and "processed_imdb_ids" in progress_data:
                    processed_count = len(progress_data["processed_imdb_ids"])
                    
                    # Load migration plan to get total count
                    migration_plan = load_json(MIGRATION_PLAN_PATH)
                    total_count = len(migration_plan.get("to_migrate", [])) if migration_plan else 0
                    
                    print(f"\n=== Migration Progress ===")
                    print(f"Movies rated so far: {processed_count}")
                    if total_count > 0:
                        print(f"Total movies to rate: {total_count}")
                        print(f"Progress: {processed_count}/{total_count} ({processed_count/total_count*100:.1f}%)")
                        print(f"Remaining: {total_count - processed_count}")
                else:
                    print("Invalid progress data format.")
            else:
                print("No progress data found. You haven't started rating movies yet.")
        elif choice == "7":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    # Create argument parser
    parser = argparse.ArgumentParser(description="Migrate Douban ratings to IMDb")
    parser.add_argument("--create-plan", action="store_true", help="Create a migration plan")
    parser.add_argument("--execute-plan", action="store_true", help="Execute the migration plan")
    parser.add_argument("--max-movies", type=int, help="Maximum number of movies to process")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode with additional debug info")
    parser.add_argument("--speed-mode", action="store_true", help="Run in speed mode (disable images for faster loading)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--proxy", type=str, help="Use proxy server (format: http://user:pass@host:port)")
    parser.add_argument("--timeout", type=int, help="Connection timeout in seconds (default: 90)")
    parser.add_argument("--retries", type=int, help="Maximum number of retries (default: 5)")
    
    args = parser.parse_args()
    
    # Set global options from command line arguments
    if args.speed_mode:
        SPEED_MODE = True
        logger.info("Running in SPEED MODE - images disabled for faster loading")
    
    if args.proxy:
        PROXY = args.proxy
        logger.info(f"Using proxy from command line: {PROXY}")
    
    if args.timeout:
        CONNECTION_TIMEOUT = args.timeout
        logger.info(f"Using custom connection timeout: {CONNECTION_TIMEOUT} seconds")
    
    if args.retries:
        MAX_RETRIES = args.retries
        logger.info(f"Using custom retry count: {MAX_RETRIES}")
    
    # Process arguments
    if args.create_plan and args.execute_plan:
        if create_migration_plan():
            # Load the migration plan
            logger.info(f"Loading migration plan from {MIGRATION_PLAN_PATH}")
            migration_plan = load_json(MIGRATION_PLAN_PATH)
            if migration_plan:
                execute_migration_plan(migration_plan, max_movies=args.max_movies, test_mode=args.test_mode)
            else:
                logger.error("Failed to load migration plan")
    elif args.create_plan:
        create_migration_plan()
    elif args.execute_plan:
        # Load the migration plan
        logger.info(f"Loading migration plan from {MIGRATION_PLAN_PATH}")
        migration_plan = load_json(MIGRATION_PLAN_PATH)
        if migration_plan:
            logger.info(f"Found {len(migration_plan.get('to_migrate', []))} movies to rate on IMDb")
            execute_migration_plan(migration_plan, max_movies=args.max_movies, test_mode=args.test_mode)
        else:
            logger.error("Failed to load migration plan")
    else:
        migrate_ratings() 