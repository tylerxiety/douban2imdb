"""
Script to export Douban ratings with manual login assistance.
"""
import os
import time
import re
import json
import logging
import random
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import chromedriver_autoinstaller
from tqdm import tqdm
from dotenv import load_dotenv
import threading
import urllib.parse
import difflib

# Handle both import cases
try:
    # When imported as a module
    from .utils import ensure_data_dir, save_json, logger, random_sleep
except ImportError:
    # When run directly
    from utils import ensure_data_dir, save_json, logger, random_sleep

# Load environment variables
load_dotenv()

# Configuration
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() in ("true", "1", "yes")
SPEED_MODE = os.getenv("SPEED_MODE", "fastest").lower()

# Derive settings from speed mode
if SPEED_MODE == "fastest":
    THROTTLING_ENABLED = False
    FAST_MODE = True
    MIN_PAGE_DELAY = 0.0
    MAX_PAGE_DELAY = 0.2
    MIN_MOVIE_DELAY = 0.0
    MAX_MOVIE_DELAY = 0.2
    DETECTED_RETRY_DELAY = 5
elif SPEED_MODE == "balanced":
    THROTTLING_ENABLED = True
    FAST_MODE = True
    MIN_PAGE_DELAY = 0.5
    MAX_PAGE_DELAY = 1.0
    MIN_MOVIE_DELAY = 0.2
    MAX_MOVIE_DELAY = 0.5
    DETECTED_RETRY_DELAY = 20
elif SPEED_MODE == "cautious":
    THROTTLING_ENABLED = True
    FAST_MODE = False
    MIN_PAGE_DELAY = 1.0
    MAX_PAGE_DELAY = 2.0
    MIN_MOVIE_DELAY = 0.5
    MAX_MOVIE_DELAY = 1.0
    DETECTED_RETRY_DELAY = 60
else:
    # Default to fastest if unrecognized mode
    THROTTLING_ENABLED = False
    FAST_MODE = True
    MIN_PAGE_DELAY = 0.0
    MAX_PAGE_DELAY = 0.2
    MIN_MOVIE_DELAY = 0.0
    MAX_MOVIE_DELAY = 0.2
    DETECTED_RETRY_DELAY = 5

# Allow overriding individual settings from environment variables
MIN_PAGE_DELAY = float(os.getenv("MIN_PAGE_DELAY", MIN_PAGE_DELAY))
MAX_PAGE_DELAY = float(os.getenv("MAX_PAGE_DELAY", MAX_PAGE_DELAY))
MIN_MOVIE_DELAY = float(os.getenv("MIN_MOVIE_DELAY", MIN_MOVIE_DELAY))
MAX_MOVIE_DELAY = float(os.getenv("MAX_MOVIE_DELAY", MAX_MOVIE_DELAY))
DETECTED_RETRY_DELAY = int(os.getenv("DETECTED_RETRY_DELAY", DETECTED_RETRY_DELAY))

# Paths
DOUBAN_EXPORT_PATH = os.getenv("DOUBAN_EXPORT_PATH", "data/douban_ratings.json")

# Thread-safe lock for appending to ratings
ratings_lock = threading.Lock()

# Counter for debug file saving
debug_movie_counter = 0
DEBUG_MOVIE_LIMIT = 10

# Counter for detection events
detection_counter = 0

# Directory for saving detection pages for later processing
DETECTION_PAGES_DIR = "debug_logs/detection_pages"

# New settings for timeout handling
PAGE_LOAD_TIMEOUT = 30  # Increased from 15 to 30 seconds
SCRIPT_TIMEOUT = 20     # Increased from 10 to 20 seconds
MAX_PAGE_RETRIES = 3    # Number of times to retry loading a page before giving up
SLOW_MODE = False       # Set to True for more stable but slower page loading

# Browser stability settings
MAX_BROWSER_INIT_ATTEMPTS = 3  # Number of attempts to initialize the browser
BROWSER_INIT_RETRY_DELAY = 5   # Seconds to wait between browser initialization attempts

def setup_browser(headless=False, attempt=1):
    """Set up and return a Selenium browser instance with performance optimizations."""
    browser = None
    try:
        # Log browser initialization attempt
        print(f"Setting up browser (attempt {attempt}/{MAX_BROWSER_INIT_ATTEMPTS})...")
        
        # Auto-install chromedriver that matches the Chrome version
        chromedriver_autoinstaller.install()
        
        chrome_options = Options()
        
        # Add common options
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Performance improvements
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disk-cache-size=104857600")  # 100MB disk cache
        chrome_options.add_argument("--blink-settings=imagesEnabled=true")  # Keep images enabled for Douban UI
        
        # Additional speed optimizations - removed problematic ones
        chrome_options.add_argument("--js-flags=--max-old-space-size=4096")  # Increase JS memory limit
        chrome_options.add_argument("--disable-features=RendererCodeIntegrity")
        
        # Enhanced anti-detection measures
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Stability improvements for large collections
        chrome_options.add_argument("--ignore-certificate-errors")
        
        # REMOVED: These options can cause stability issues
        # chrome_options.add_argument("--disable-features=site-per-process")
        # chrome_options.add_argument("--disable-ipc-flooding-protection")
        # chrome_options.add_argument("--disable-web-security")
        # chrome_options.add_argument("--single-process")
        
        # Browser crash reporting - helpful for diagnosing issues
        chrome_options.add_argument("--enable-crash-reporter")
        
        # If we're on retry attempts, force headless mode as it's more stable
        if attempt > 1:
            headless = True
            print("Using more stable headless mode for retry attempt")
        
        # Add widely used user agent
        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ]
        chrome_options.add_argument(f"--user-agent={random.choice(user_agents)}")
        
        # Add window size randomization for more human-like behavior
        if headless:
            chrome_options.add_argument("--headless=new")
            resolutions = [(1920, 1080), (1440, 900), (1366, 768)]
            chosen_res = random.choice(resolutions)
            chrome_options.add_argument(f"--window-size={chosen_res[0]},{chosen_res[1]}")
        
        # Create diagnostic directory if needed
        os.makedirs("debug_logs", exist_ok=True)
        
        # Log Chrome version
        import subprocess
        try:
            chrome_version_cmd = 'google-chrome --version' if os.name == 'posix' else 'reg query "HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon" /v version'
            chrome_version = subprocess.check_output(chrome_version_cmd, shell=True).decode().strip()
            print(f"Chrome version: {chrome_version}")
            with open(os.path.join("debug_logs", "chrome_version.txt"), "w") as f:
                f.write(f"Chrome version: {chrome_version}\n")
                f.write(f"Options: {str(chrome_options.arguments)}\n")
        except:
            print("Could not determine Chrome version")
        
        # Create browser with a short timeout to catch immediate crashes
        browser = webdriver.Chrome(options=chrome_options)
        
        # Test browser stability by running a simple script
        browser.execute_script("return navigator.userAgent;")
        print("Browser initialized successfully!")
        
        # Set page load timeout to prevent hanging on slow pages
        global PAGE_LOAD_TIMEOUT, SCRIPT_TIMEOUT
        browser.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        
        # Set script timeout for JavaScript execution
        browser.set_script_timeout(SCRIPT_TIMEOUT)
        
        # Additional anti-detection measures
        if not headless:
            # Make the browser window appear more human-like
            browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Double check session is active
        browser.execute_script("return document.title;")
        
        logger.info("Browser set up with enhanced anti-detection and performance optimizations")
        return browser
        
    except Exception as e:
        print(f"Browser initialization failed: {e}")
        logger.error(f"Browser initialization failed: {e}")
        
        # Save error information for debugging
        with open(os.path.join("debug_logs", f"browser_init_error_{attempt}.txt"), "w") as f:
            f.write(f"Error: {str(e)}\n")
        
        # Try to quit the browser if it exists but failed
        if browser:
            try:
                browser.quit()
            except:
                pass
        
        # Retry browser initialization if we haven't exceeded max attempts
        if attempt < MAX_BROWSER_INIT_ATTEMPTS:
            print(f"Retrying browser initialization in {BROWSER_INIT_RETRY_DELAY} seconds...")
            time.sleep(BROWSER_INIT_RETRY_DELAY)
            return setup_browser(headless=True, attempt=attempt+1)
        else:
            print("Failed to initialize browser after maximum attempts")
            raise

def login_to_douban_manually(browser):
    """Navigate to Douban and assist with manual login."""
    print("\n=== MANUAL LOGIN REQUIRED ===")
    print("1. A browser window will open to Douban")
    print("2. Please log in manually (find the login button, enter credentials, scan QR code if needed)")
    print("3. Make sure you're fully logged in before continuing")
    print("NOTE: If the page seems stuck loading, you can still proceed once you've logged in successfully")
    
    try:
        # Navigate to Douban
        try:
            browser.get("https://www.douban.com/")
        except TimeoutException:
            print("\nThe page timed out while loading, but you may still be able to log in.")
            print("If you can see the Douban login page, please proceed with login.")
        except Exception as e:
            print(f"\nError loading Douban: {e}")
            print("Please try again or check your internet connection.")
            return False
        
        # Wait for user to confirm login
        input("\nPress Enter AFTER you have successfully logged in to Douban...")
        
        # Ask user to explicitly confirm login success
        confirmation = input("Did you successfully log in to Douban? (y/n): ")
        if confirmation.lower() not in ['y', 'yes']:
            print("Login not confirmed. Exiting.")
            return False
        
        print("Login confirmed. Proceeding with extraction.")
        return True
            
    except Exception as e:
        logger.error(f"Error during login process: {e}")
        # Still give the user a chance to confirm if login was successful
        confirmation = input("Despite errors, were you able to successfully log in? (y/n): ")
        return confirmation.lower() in ['y', 'yes']

def get_user_id_manually(browser):
    """Get the Douban user ID manually."""
    print("\n=== DOUBAN USER ID REQUIRED ===")
    print("Enter your Douban user ID or numeric ID.")
    print("You can find this in your profile URL: https://www.douban.com/people/YOUR_ID/")
    user_id = input("Your Douban user ID: ")
    
    if not user_id:
        # Try to navigate to user page and extract ID
        browser.get("https://www.douban.com/mine/")
        time.sleep(2)
        
        try:
            # Find profile link
            profile_link = browser.find_element(By.CSS_SELECTOR, ".nav-user-account a")
            profile_url = profile_link.get_attribute("href")
            extracted_id = profile_url.split('/')[-2]
            
            if extracted_id:
                print(f"Found user ID from profile: {extracted_id}")
                confirmation = input(f"Use this ID? (y/n): ")
                if confirmation.lower() in ['y', 'yes']:
                    return extracted_id
                
                # Ask again for manual entry
                user_id = input("Your Douban user ID: ")
        except Exception as e:
            logger.error(f"Could not extract user ID: {e}")
            user_id = input("Your Douban user ID (manual entry required): ")
    
    return user_id

def search_imdb_for_movie(browser, title, year, english_title=None):
    """
    Search IMDb directly for a movie using title and year.
    This is a fallback method when we can't find the IMDb ID on Douban.
    
    Args:
        browser: Selenium browser instance
        title: Movie title in original language
        year: Release year as string
        english_title: Optional English title for better matching
    
    Returns:
        IMDb ID if found, None otherwise
    """
    try:
        # Set a shorter timeout for IMDb searches to avoid hanging
        original_timeout = browser.timeouts.page_load
        browser.set_page_load_timeout(8)  # Reduced from default to avoid long hanging
        
        # Determine the best search term to use
        search_title = english_title if english_title else title
        
        # Remove any non-essential phrases from the title that might affect search
        search_title = re.sub(r'\([^)]*\)', '', search_title)  # Remove parenthesized text
        search_title = re.sub(r'第\d+季.*', '', search_title)  # Remove Chinese season indicators
        search_title = re.sub(r'Season\s*\d+.*', '', search_title, flags=re.IGNORECASE)  # Remove English season indicators
        search_title = re.sub(r'\s*\d+x\d+\s*', ' ', search_title)  # Remove episode format like "1x01"
        search_title = re.sub(r'\s*S\d+E\d+\s*', ' ', search_title, flags=re.IGNORECASE)  # Remove episode format like "S01E01"
        search_title = search_title.strip()
        
        # Prepare the IMDb search URL
        if year:
            # If we have the year, include it in the search query for better accuracy
            search_query = f"{search_title} {year}"
        else:
            search_query = search_title
            
        encoded_query = urllib.parse.quote_plus(search_query)
        imdb_search_url = f"https://www.imdb.com/find/?q={encoded_query}&s=tt&ttype=ft"
        
        logger.debug(f"Searching IMDb for: {search_query}")
        
        # Navigate to the search results page
        try:
            browser.get(imdb_search_url)
        except TimeoutException:
            # If the page times out, try to work with what we have
            print(f"IMDb search timed out, but attempting to extract results anyway...")
            # Continue with extraction despite timeout
        except Exception as e:
            logger.warning(f"Error accessing IMDb: {e}")
            return None
        
        # Wait for search results to load with shorter timeout
        try:
            WebDriverWait(browser, 3).until(  # Reduced from 5 to 3
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ipc-metadata-list-summary-item"))
            )
        except:
            # If wait times out, just continue with whatever loaded
            print("Wait for IMDb results timed out, trying extraction anyway...")
        
        # First try: Look for direct search results using JavaScript with a timeout
        try:
            # Set script timeout to prevent hanging
            original_script_timeout = browser.timeouts.script
            browser.set_script_timeout(4)  # Short timeout for script execution
            
            js_extraction = """
            try {
                // Find all search result items
                const resultItems = document.querySelectorAll('.ipc-metadata-list-summary-item');
                
                if (resultItems.length > 0) {
                    // Function to extract year from result
                    function extractYear(item) {
                        const yearText = item.querySelector('.ipc-metadata-list-summary-item__tl');
                        if (yearText) {
                            const yearMatch = yearText.textContent.match(/(\\d{4})/);
                            return yearMatch ? yearMatch[1] : null;
                        }
                        return null;
                    }
                    
                    // First result should be the most relevant
                    const firstResult = resultItems[0];
                    const resultLink = firstResult.querySelector('a');
                    
                    if (resultLink) {
                        const href = resultLink.getAttribute('href');
                        const idMatch = href.match(/\\/title\\/(tt\\d+)/);
                        
                        if (idMatch) {
                            // Check if this is the correct year if we have year info
                            const yearArg = arguments[0];
                            
                            if (yearArg) {
                                const resultYear = extractYear(firstResult);
                                
                                // If year matches exactly, this is almost certainly the right movie
                                if (resultYear === yearArg) {
                                    return idMatch[1];
                                }
                                
                                // If year is within 1 year difference, probably the right movie
                                // (accounts for different release years in different regions)
                                if (resultYear && Math.abs(parseInt(resultYear) - parseInt(yearArg)) <= 1) {
                                    return idMatch[1];
                                }
                                
                                // If the years don't match, check the next few results
                                for (let i = 1; i < Math.min(3, resultItems.length); i++) {
                                    const nextResult = resultItems[i];
                                    const nextLink = nextResult.querySelector('a');
                                    const nextYear = extractYear(nextResult);
                                    
                                    if (nextLink && nextYear && (nextYear === yearArg || 
                                        Math.abs(parseInt(nextYear) - parseInt(yearArg)) <= 1)) {
                                        const nextHref = nextLink.getAttribute('href');
                                        const nextIdMatch = nextHref.match(/\\/title\\/(tt\\d+)/);
                                        if (nextIdMatch) {
                                            return nextIdMatch[1];
                                        }
                                    }
                                }
                            }
                            
                            // If no year match or no year provided, return the first result
                            return idMatch[1];
                        }
                    }
                }
                
                // No results found via standard search, try checking for a "Did you mean" suggestion
                const didYouMean = document.querySelector('.findDidYouMean a');
                if (didYouMean) {
                    const href = didYouMean.getAttribute('href');
                    const idMatch = href.match(/\\/title\\/(tt\\d+)/);
                    if (idMatch) {
                        return idMatch[1];
                    }
                }
                
                return null;
            } catch (e) {
                console.error("Error searching IMDb:", e);
                return null;
            }
            """
            imdb_id = browser.execute_script(js_extraction, year)
            
            # Reset script timeout
            browser.set_script_timeout(original_script_timeout)
            
            if imdb_id:
                logger.debug(f"Found IMDb ID via direct search: {imdb_id}")
                return imdb_id
        except Exception as e:
            # Log but continue to next method
            print(f"JavaScript extraction error: {str(e)[:100]}")
            try:
                # Try to reset script timeout if possible
                browser.set_script_timeout(original_script_timeout)
            except:
                pass
        
        # Fallback to BeautifulSoup parsing
        try:
            soup = BeautifulSoup(browser.page_source, 'html.parser')
            
            # Extract all search results
            result_items = soup.select('.ipc-metadata-list-summary-item')
            
            if result_items:
                # Helper function to evaluate title similarity
                def title_similarity(a, b):
                    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
                
                # Helper function to extract year from result item
                def extract_year(item):
                    year_elem = item.select_one('.ipc-metadata-list-summary-item__tl')
                    if year_elem:
                        year_match = re.search(r'(\d{4})', year_elem.text)
                        return year_match.group(1) if year_match else None
                    return None
                
                # Set of titles to check similarity against
                titles_to_check = {search_title}
                # Add original title if using English title
                if english_title and english_title != title:
                    titles_to_check.add(title)
                
                best_match = None
                best_match_score = 0
                
                # Check the first 5 results at most
                for idx, item in enumerate(result_items[:5]):
                    link = item.select_one('a')
                    if not link:
                        continue
                        
                    href = link.get('href', '')
                    id_match = re.search(r'/title/(tt\d+)', href)
                    if not id_match:
                        continue
                        
                    result_id = id_match.group(1)
                    result_title = link.text.strip()
                    result_year = extract_year(item)
                    
                    # Calculate similarity scores for all our titles
                    max_similarity = max(title_similarity(result_title, t) for t in titles_to_check)
                    
                    # Adjust score based on year match
                    year_bonus = 0
                    if year and result_year:
                        if year == result_year:
                            year_bonus = 0.3  # Exact year match is a strong signal
                        elif abs(int(year) - int(result_year)) <= 1:
                            year_bonus = 0.15  # Within 1 year is also good
                            
                    total_score = max_similarity + year_bonus
                    
                    # Favor first result slightly for IMDb relevance
                    if idx == 0:
                        total_score += 0.05
                        
                    if total_score > best_match_score:
                        best_match = result_id
                        best_match_score = total_score
                
                # Only return if we have a reasonably good match
                if best_match_score > 0.6:  # Threshold can be adjusted
                    logger.debug(f"Found IMDb ID via BeautifulSoup: {best_match} (score: {best_match_score:.2f})")
                    return best_match
            
            # Check for "Did you mean" suggestion
            did_you_mean = soup.select_one('.findDidYouMean a')
            if did_you_mean:
                href = did_you_mean.get('href', '')
                id_match = re.search(r'/title/(tt\d+)', href)
                if id_match:
                    return id_match.group(1)
        
        except Exception as e:
            logger.warning(f"BeautifulSoup search extraction failed: {str(e)[:100]}")
            
        return None
    except Exception as e:
        logger.error(f"Error searching IMDb: {str(e)[:100]}")
        return None
    finally:
        # Reset any browser settings we might have changed
        try:
            browser.set_page_load_timeout(original_timeout)
        except:
            browser.set_page_load_timeout(15)  # Default fallback

def save_debug_movie_html(browser, douban_id, title=None):
    """Save the HTML of a movie page for debugging purposes."""
    # Skip if in fast mode
    if FAST_MODE:
        return None
    
    global debug_movie_counter
    if debug_movie_counter < DEBUG_MOVIE_LIMIT:
        try:
            # Ensure the debug directory exists
            debug_dir = "debug_logs/movie_pages"
            os.makedirs(debug_dir, exist_ok=True)
            
            # Create a filename with timestamp, douban id and truncated title
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title or str(douban_id))[:50]  # Remove invalid chars and truncate
            filename = f"{debug_movie_counter+1:02d}_{douban_id}_{safe_title}_{timestamp}.html"
            filepath = os.path.join(debug_dir, filename)
            
            # Save the HTML content
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(browser.page_source)
            
            logger.info(f"Saved debug HTML for movie {douban_id} to {filepath}")
            print(f"Saved debug HTML for movie {title or douban_id} ({douban_id})")
            
            debug_movie_counter += 1
            return filepath
        except Exception as e:
            logger.error(f"Error saving debug HTML: {e}")
    return None

def extract_imdb_id(browser, douban_url, title=None, year=None, english_title=None):
    """Extract IMDb ID from Douban movie page with improved precision."""
    douban_id = None
    try:
        # Extract douban_id from the URL for debug logging
        douban_id_match = re.search(r"subject/(\d+)", douban_url)
        if douban_id_match:
            douban_id = douban_id_match.group(1)
        
        # Set a shorter timeout for faster processing
        browser.set_page_load_timeout(10)  # Reduced from 15 to 10
        
        print(f"Accessing: {douban_url}")
        try:
            # Minimal delay based on throttling status
            if THROTTLING_ENABLED:
                time.sleep(random.uniform(0.5, 1.5))
            # Zero delay if throttling is disabled
                
            browser.get(douban_url)
            
            # Check for detection immediately after loading page
            if check_for_detection(browser):
                print(f"⚠️ Detection alert on movie page.")
                # Save the page for later processing instead of waiting and retrying
                global detection_counter
                detection_counter += 1
                
                # Create directory if it doesn't exist
                os.makedirs(DETECTION_PAGES_DIR, exist_ok=True)
                
                # Save the HTML with douban ID and title for later processing
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title or str(douban_id))[:50]
                filename = f"detection_{douban_id}_{safe_title}_{timestamp}.html"
                filepath = os.path.join(DETECTION_PAGES_DIR, filename)
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(browser.page_source)
                
                print(f"Saved detection page for later processing (#{detection_counter})")
                
                # Return None to move on to the next movie
                return None
            
            # Wait for content to load - shorter timeout
            try:
                # Wait for either the info section or subject-info section to load
                WebDriverWait(browser, 5).until(  # Reduced timeout from 10 to 5
                    lambda b: b.find_element(By.ID, "info") is not None or 
                              b.find_element(By.CSS_SELECTOR, ".subject-info") is not None
                )
            except:
                # Continue anyway, don't waste time logging
                pass
                
            # Only add human-like browsing behavior if throttling is enabled
            if THROTTLING_ENABLED:
                add_human_browsing_behavior(browser)
                
            # Save debug HTML only if needed
            if not FAST_MODE and debug_movie_counter < DEBUG_MOVIE_LIMIT:
                save_debug_movie_html(browser, douban_id, title)
            
        except TimeoutException:
            # Don't log a warning, just move on
            pass
        except Exception as e:
            # Keep errors brief for speed
            logger.warning(f"Error loading page: {e}")
            return None
        
        # FIRST METHOD: Extract using JavaScript with multiple precise strategies
        try:
            # Use the same JavaScript but with faster execution
            imdb_id = browser.execute_script(js_script)
            if imdb_id:
                print(f"Found IMDb ID: {imdb_id}")
                return imdb_id
                
        except Exception as e:
            # Don't log details to improve speed
            pass
        
        # SECOND METHOD: Only use BeautifulSoup if JS fails
        html_content = browser.page_source
        imdb_id = extract_imdb_id_from_html(html_content)
        if imdb_id:
            print(f"Found IMDb ID: {imdb_id}")
            return imdb_id
            
        # Skip direct IMDb search unless explicitly requested - it's slow
        # Only do this if throttling is disabled and fast mode is off
        if title and year and not THROTTLING_ENABLED and not FAST_MODE:
            logger.info(f"Trying IMDb search for '{title}'")
            return search_imdb_for_movie(browser, title, year, english_title)
        else:
            print(f"No IMDb ID found")
            return None
            
    except Exception as e:
        logger.warning(f"Error: {e}")
        return None
    finally:
        # Reset page load timeout to default
        browser.set_page_load_timeout(15)

def extract_imdb_id_from_html(html_content):
    """Extract IMDb ID from HTML content using BeautifulSoup with precise patterns."""
    try:
        # Use a specific parser for better performance
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # PATTERN 1: Look for IMDb ID in direct links (most reliable)
        imdb_links = soup.select('a[href*="imdb.com/title/"]')
        for link in imdb_links:
            href = link.get('href', '')
            match = re.search(r'title/(tt\d+)', href)
            if match:
                return match.group(1)
        
        # PATTERN 2: Check the info section with very specific Douban patterns
        info_section = soup.select_one("#info")
        if info_section:
            # Check for the common Douban format: "IMDb: tt0000000"
            info_text = info_section.text
            
            # Look for "IMDb:" pattern with colon - this is very common on Douban
            imdb_label_match = re.search(r'IMDb[：:][^\n]*(tt\d{7,10})', info_text, re.IGNORECASE)
            if imdb_label_match:
                return imdb_label_match.group(1)
            
            # Look for any tt pattern in info section
            tt_pattern_match = re.search(r'\b(tt\d{7,10})\b', info_text)
            if tt_pattern_match:
                return tt_pattern_match.group(1)
            
            # Douban often has span elements with specific structure
            spans = info_section.select('span')
            for span in spans:
                span_text = span.text
                if 'IMDb' in span_text:
                    # Try to find IMDb ID in this span
                    id_match = re.search(r'\b(tt\d{7,10})\b', span_text)
                    if id_match:
                        return id_match.group(1)
                    
                    # If the span contains "IMDb:" but not the ID, check next siblings
                    next_element = span.next_sibling
                    for _ in range(3):  # Check next few siblings
                        if next_element and isinstance(next_element, str):
                            id_match = re.search(r'\b(tt\d{7,10})\b', next_element)
                            if id_match:
                                return id_match.group(1)
                        elif next_element:
                            id_match = re.search(r'\b(tt\d{7,10})\b', next_element.text if hasattr(next_element, 'text') else '')
                            if id_match:
                                return id_match.group(1)
                        
                        if next_element:
                            next_element = next_element.next_sibling
                        else:
                            break
        
        # PATTERN 3: Check modern Douban layout with subject-info structure
        subject_info = soup.select_one('.subject-info')
        if subject_info:
            subject_text = subject_info.text
            
            # Check for IMDb label format
            subject_label_match = re.search(r'IMDb[：:][^\n]*(tt\d{7,10})', subject_text, re.IGNORECASE)
            if subject_label_match:
                return subject_label_match.group(1)
            
            # Check for any tt pattern
            subject_tt_match = re.search(r'\b(tt\d{7,10})\b', subject_text)
            if subject_tt_match:
                return subject_tt_match.group(1)
            
            # Check all elements in subject-info
            for elem in subject_info.find_all():
                elem_text = elem.text
                if 'IMDb' in elem_text:
                    id_match = re.search(r'\b(tt\d{7,10})\b', elem_text)
                    if id_match:
                        return id_match.group(1)
        
        # PATTERN 4: Look for specific elements that might contain IMDb ID
        # Sometimes Douban has IMDb ID in div elements
        imdb_divs = [div for div in soup.find_all('div') if 'IMDb' in div.text]
        for div in imdb_divs:
            id_match = re.search(r'\b(tt\d{7,10})\b', div.text)
            if id_match:
                return id_match.group(1)
        
        # PATTERN 5: Try looking for specific douban-related elements
        # Douban might have IMDb data in other structured elements
        for elem in soup.select('.pl'):  # Common Douban class for labels
            if 'IMDb' in elem.text:
                # Check this element and siblings
                next_elem = elem.next_sibling
                for _ in range(3):
                    if next_elem and isinstance(next_elem, str):
                        id_match = re.search(r'\b(tt\d{7,10})\b', next_elem)
                        if id_match:
                            return id_match.group(1)
                    elif next_elem:
                        id_match = re.search(r'\b(tt\d{7,10})\b', next_elem.text if hasattr(next_elem, 'text') else '')
                        if id_match:
                            return id_match.group(1)
                    
                    if next_elem:
                        next_elem = next_elem.next_sibling
                    else:
                        break
        
        # PATTERN 6: Last resort - check the entire HTML for IMDb ID pattern
        # Check the whole page for IMDb ID near IMDb text
        full_text_match = re.search(r'IMDb[：:][^\n]*?(tt\d{7,10})', str(soup), re.IGNORECASE)
        if full_text_match:
            return full_text_match.group(1)
        
        # Just find any IMDb ID in the HTML
        imdb_id_match = re.search(r'\b(tt\d{7,10})\b', str(soup))
        if imdb_id_match:
            return imdb_id_match.group(1)
        
        return None
    except Exception as e:
        logger.warning(f"Error extracting IMDb ID from HTML: {e}")
        return None

def extract_us_year(info_text):
    """
    Extract the US release year from the info text.
    Looks for patterns like "YYYY-MM-DD(美国)" or "YYYY(美国)"
    """
    # Try to find specific US release date pattern: YYYY-MM-DD(美国)
    us_date_match = re.search(r'(\d{4})(?:-\d{2}-\d{2})?\s*(?:\([^)]*美国[^)]*\))', info_text)
    if us_date_match:
        return us_date_match.group(1)
    
    # Try to find any year associated with US: YYYY(美国) or (美国) YYYY
    us_year_match = re.search(r'(?:(\d{4})\s*\([^)]*美国[^)]*\))|(?:\([^)]*美国[^)]*\)\s*(\d{4}))', info_text)
    if us_year_match:
        return us_year_match.group(1) or us_year_match.group(2)
    
    # If no US year, try to find the first year in the info
    first_year_match = re.search(r'(\d{4})', info_text)
    if first_year_match:
        return first_year_match.group(1)
    
    return None

def fetch_movie_ratings(browser, user_id, include_details=False, use_efficient_mode=False, skip_imdb=False, max_workers=2):
    """
    Fetch all movie ratings for the given user.
    
    Args:
        browser: Selenium browser instance
        user_id: Douban user ID
        include_details: Whether to include detailed information (info text) in the output
        use_efficient_mode: No longer used - kept for backward compatibility
        skip_imdb: Skip IMDb extraction entirely (can be done later)
        max_workers: No longer used - kept for backward compatibility
    """
    # Check if ratings file exists to resume from
    if os.path.exists(DOUBAN_EXPORT_PATH):
        try:
            print(f"\nExisting ratings file found at {DOUBAN_EXPORT_PATH}")
            with open(DOUBAN_EXPORT_PATH, 'r', encoding='utf-8') as f:
                existing_ratings = json.load(f)
                
            if existing_ratings and isinstance(existing_ratings, list):
                print(f"Loaded {len(existing_ratings)} existing ratings")
                if input("Resume from existing file? (y/n, default: y): ").lower() != 'n':
                    ratings = existing_ratings
                    # Extract processed IDs from existing ratings
                    processed_douban_ids = {r['douban_id'] for r in ratings if 'douban_id' in r}
                    print(f"Will skip {len(processed_douban_ids)} already processed movies")
                    
                    # Show stats about IMDb IDs
                    movies_with_imdb = sum(1 for r in ratings if r.get('imdb_id'))
                    if movies_with_imdb < len(ratings):
                        print(f"Note: {movies_with_imdb}/{len(ratings)} movies have IMDb IDs ({movies_with_imdb/len(ratings)*100:.1f}%)")
                        
                    # Ask if the user wants to re-process movies without IMDb IDs
                    if not skip_imdb and movies_with_imdb < len(ratings):
                        reprocess = input("Re-process movies without IMDb IDs? (y/n, default: n): ").lower() == 'y'
                        if reprocess:
                            # Remove from processed_douban_ids so they get processed again
                            missing_imdb_ids = {r['douban_id'] for r in ratings if 'douban_id' in r and 'imdb_id' not in r}
                            processed_douban_ids -= missing_imdb_ids
                            print(f"Will re-process {len(missing_imdb_ids)} movies without IMDb IDs")
                    
                    # Continue with the loaded ratings
                    start_ratings = ratings
                else:
                    # Start fresh
                    ratings = []
                    processed_douban_ids = set()
                    start_ratings = []
            else:
                print("Invalid ratings file format. Starting fresh.")
                ratings = []
                processed_douban_ids = set()
                start_ratings = []
        except Exception as e:
            print(f"Error loading existing ratings: {e}")
            print("Starting fresh.")
            ratings = []
            processed_douban_ids = set()
            start_ratings = []
    else:
        print("No existing ratings file found. Starting fresh.")
        ratings = []
        processed_douban_ids = set()
        start_ratings = []
    
    page = 1
    has_next_page = True
    items_processed = 0
    imdb_extraction_failures = 0
    max_imdb_failures = 20  # Increased for more tolerance
    imdb_extraction_success = 0  # Track successful extractions
    max_pages = 1000  # Set a high max page limit to ensure we get all ratings
    max_empty_pages = 10  # Increased from 3 to 10 for better tolerance
    consecutive_empty_pages = 0
    
    # Allow user to specify start page and total pages
    start_page = 1
    manual_max_pages = None
    
    # Ask if user wants to specify page range
    if input("\nSpecify page range? (For very large collections) (y/n, default: n): ").lower() == 'y':
        try:
            start_page_input = input("Start from page (default: 1): ")
            if start_page_input and start_page_input.isdigit():
                start_page = max(1, int(start_page_input))
                page = start_page
            
            max_pages_input = input("Maximum pages to process (default: all): ")
            if max_pages_input and max_pages_input.isdigit():
                manual_max_pages = int(max_pages_input)
                max_pages = manual_max_pages
                
            print(f"Will process pages {start_page} to {start_page + max_pages - 1 if manual_max_pages else 'end'}")
        except:
            print("Invalid input. Using defaults.")
    
    # Create progress bar
    pbar = tqdm(desc="Fetching Douban ratings", unit="page")
    
    # Always operate in sequential mode
    use_efficient_mode = False
    max_workers = 1
    
    # Reset detection counter
    global detection_counter
    detection_counter = 0
    
    # Set browser timeout for large collections
    global SLOW_MODE
    if SLOW_MODE:
        print("Slow mode is enabled - using extended timeouts for better stability")
        browser.set_page_load_timeout(PAGE_LOAD_TIMEOUT * 2)  # Double the timeout in slow mode
    
    try:
        while has_next_page and page <= max_pages:
            # Construct URL with page parameter
            url = f"https://movie.douban.com/people/{user_id}/collect?start={(page-1)*15}&sort=time&rating=all&filter=all&mode=grid"
            
            print(f"\nPage {page}...")
            
            # Track retries for this page
            page_retry_count = 0
            page_loaded = False
            
            while not page_loaded and page_retry_count < MAX_PAGE_RETRIES:
                try:
                    # Minimal delay between pages when throttling is disabled
                    if THROTTLING_ENABLED:
                        delay = random.uniform(MIN_PAGE_DELAY, MAX_PAGE_DELAY)
                        print(f"Waiting {delay:.1f}s...")
                        time.sleep(delay)
                    elif SLOW_MODE:
                        # Small delay even if throttling is disabled in slow mode
                        time.sleep(random.uniform(0.5, 1.0))
                    
                    # Try to load the page with timeout handling
                    print(f"Loading page (attempt {page_retry_count + 1}/{MAX_PAGE_RETRIES})...")
                    browser.get(url)
                    page_loaded = True
                    
                except TimeoutException:
                    page_retry_count += 1
                    print(f"⚠️ Page load timed out after {PAGE_LOAD_TIMEOUT}s.")
                    
                    if page_retry_count < MAX_PAGE_RETRIES:
                        # Take a short break before retrying
                        retry_delay = 3 + (page_retry_count * 2)  # Increase delay with each retry
                        print(f"Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        
                        # Try refreshing the page first before a full reload
                        try:
                            browser.refresh()
                            time.sleep(1)
                        except:
                            pass
                    else:
                        print(f"Failed to load page after {MAX_PAGE_RETRIES} attempts. Skipping to next page.")
                        page += 1
                        pbar.update(1)
                        continue
                        
                except Exception as e:
                    # Generic error handling
                    print(f"Error loading page: {e}")
                    page_retry_count += 1
                    
                    if page_retry_count < MAX_PAGE_RETRIES:
                        # Take a short break before retrying
                        retry_delay = 3 + (page_retry_count * 2)
                        print(f"Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        print(f"Failed to load page after {MAX_PAGE_RETRIES} attempts. Skipping to next page.")
                        page += 1
                        pbar.update(1)
                        continue
            
            # If we get here and page is not loaded, move to next page
            if not page_loaded:
                page += 1
                pbar.update(1)
                continue
            
            # Check for "abnormal requests" message immediately
            if check_for_detection(browser):
                print(f"⚠️ Detection alert on ratings page.")
                
                # Save the page for later analysis
                if not FAST_MODE:
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    os.makedirs(DETECTION_PAGES_DIR, exist_ok=True)
                    log_path = os.path.join(DETECTION_PAGES_DIR, f"ratings_page_{page}_{timestamp}.html")
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(browser.page_source)
                    print(f"Saved detection page for reference")
                
                # Just take a quick break and try the next page
                print(f"Trying next page...")
                time.sleep(1)  # Extremely short delay
                page += 1
                pbar.update(1)
                continue
            
            # Wait for content to load with more robust selectors
            content_loaded = False
            try:
                # Use a longer timeout for content loading in slow mode
                wait_timeout = 20 if SLOW_MODE else 10
                WebDriverWait(browser, wait_timeout).until(
                    lambda b: (
                        len(b.find_elements(By.CSS_SELECTOR, ".item.comment-item")) > 0 or
                        len(b.find_elements(By.CSS_SELECTOR, ".grid-view .item")) > 0 or
                        len(b.find_elements(By.CSS_SELECTOR, ".list-view .item")) > 0 or
                        len(b.find_elements(By.CSS_SELECTOR, ".info h2")) > 0 or  # Empty results indicator
                        "没有找到符合条件的条目" in b.page_source  # "No items found" text
                    )
                )
            except:
                # Wait a bit longer if timeout
                print("Waiting for page content to load...")
                time.sleep(5.0)  # Increased from 3.0 to 5.0
                
                try:
                    # One more attempt with shorter selectors
                    WebDriverWait(browser, 5).until(
                        lambda b: (
                            len(b.find_elements(By.CSS_SELECTOR, ".item")) > 0 or
                            "没有找到" in b.page_source  # Simplified "No items found" text
                        )
                    )
                except:
                    # Continue anyway - we'll handle empty pages below
                    pass
            
            # Debug output for pagination
            print("Analyzing page content...")
            
            # Save HTML for debugging on empty pages to diagnose the issue
            if not FAST_MODE or consecutive_empty_pages > 0:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                os.makedirs("debug_logs", exist_ok=True)
                log_path = os.path.join("debug_logs", f"douban_ratings_page_{page}_{timestamp}.html")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(browser.page_source)
                print(f"Saved page HTML for debugging")
            
            # Only add browsing behavior if throttling is enabled (it's slow)
            if THROTTLING_ENABLED:
                add_human_browsing_behavior(browser)
                
            # Parse the page
            soup = BeautifulSoup(browser.page_source, 'html.parser')
            
            # Try multiple selectors for movie items with expanded patterns
            movie_items = []
            selectors = [
                ".item.comment-item",  # Standard selector for movie items
                ".grid-view .item",    # Grid view selector
                ".list-view .item",    # List view selector
                "[data-item_id]",      # Items with data-item_id attribute
                ".subject-item"        # Alternative item class
            ]
            
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    movie_items = items
                    print(f"Found {len(items)} movies using selector: {selector}")
                    break
            
            # Debug pagination elements
            pagination = soup.select_one(".paginator")
            if pagination:
                print("Pagination found.")
                # Check all page links
                page_links = pagination.select("a")
                page_numbers = [link.text.strip() for link in page_links if link.text.strip().isdigit()]
                print(f"Page numbers in pagination: {', '.join(page_numbers)}")
                
                # Check next link specifically
                next_link = pagination.select_one(".next")
                if next_link:
                    print("Next page link found.")
                else:
                    print("Next page link NOT found.")
                    
                # Check for disable-link class which indicates last page
                if pagination.select_one(".next.disable-link") or pagination.select_one(".disable-link"):
                    print("Disable link found - likely the last page.")
            else:
                print("No pagination element found.")
            
            if not movie_items:
                consecutive_empty_pages += 1
                print(f"Empty page {consecutive_empty_pages}/{max_empty_pages}")
                
                # Save more detailed debug info for empty pages
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                debug_path = os.path.join("debug_logs", f"empty_page_{page}_{timestamp}.html")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(browser.page_source)
                print(f"Saved empty page HTML for detailed analysis")
                
                # More robust check for pagination
                has_pagination = False
                has_next = False
                
                # Multiple ways to check for pagination
                if pagination:
                    has_pagination = True
                    next_link = pagination.select_one(".next")
                    has_next = next_link and "disable-link" not in next_link.get("class", [])
                
                # Check URL parameters to see if we're on a valid page
                start_param = (page-1)*15
                if start_param > 0 and "start=" + str(start_param) in browser.current_url:
                    # We're on a valid page, might be empty
                    print(f"Valid page URL, but no movies found.")
                    
                # Check for empty page message or "none found" text
                if "没有找到符合条件的条目" in browser.page_source or "No items found" in browser.page_source:
                    print("Found 'No items found' message.")
                
                # More aggressively continue to next page
                if not has_pagination or not has_next:
                    # Check if we're at a page that should exist
                    if manual_max_pages and page >= start_page + manual_max_pages - 1:
                        print("Reached manually specified maximum page.")
                        break
                        
                    # If we think there should be more pages, forcibly try next page
                    if consecutive_empty_pages < max_empty_pages:
                        print("No pagination found, but trying next page anyway...")
                        page += 1
                        pbar.update(1)
                        continue
                    else:
                        print("Too many consecutive empty pages. No pagination found.")
                        break
                
                # If we've hit too many consecutive empty pages, assume we're done
                if consecutive_empty_pages >= max_empty_pages:
                    print(f"Too many empty pages. Ending search.")
                    break
                    
                # Try next page
                page += 1
                pbar.update(1)
                continue
            else:
                # Reset consecutive empty page counter when we find movies
                consecutive_empty_pages = 0
            
            for item_index, item in enumerate(movie_items):
                try:
                    # Extract movie info
                    # Try multiple title selectors for greater robustness
                    title_elem = None
                    for title_selector in [".title a", "h2 a", ".info h2 a", "a.title", ".title > a", "[href*='/subject/']"]:
                        title_elem = item.select_one(title_selector)
                        if title_elem:
                            break
                            
                    if not title_elem:
                        # Try to find any link that might contain the movie URL
                        for link in item.select("a"):
                            href = link.get("href", "")
                            if "/subject/" in href:
                                title_elem = link
                                break
                                
                    if not title_elem:
                        print("Could not find title element, skipping item")
                        continue
                        
                    title = title_elem.text.strip()
                    douban_url = title_elem["href"]
                    douban_id_match = re.search(r"subject/(\d+)", douban_url)
                    if not douban_id_match:
                        print(f"Could not extract Douban ID from URL: {douban_url}")
                        continue
                    douban_id = douban_id_match.group(1)
                    
                    # Skip if we've already processed this movie
                    if douban_id in processed_douban_ids:
                        print(f"Skipping: {title}")
                        continue
                    else:
                        processed_douban_ids.add(douban_id)
                    
                    # Extract rating with expanded patterns
                    rating_value = None
                    
                    # Look for rating class directly in li element
                    rating_spans = item.select("li span[class^='rating'], span[class^='rating'], span.rating, .rating span, .star .rating")
                    if rating_spans:
                        for span in rating_spans:
                            span_class = ' '.join(span.get('class', []))
                            rating_match = re.search(r'rating(\d)', span_class)
                            if rating_match:
                                rating_value = int(rating_match.group(1))
                                break
                    
                    # Fallback to checking any element with a rating class
                    if rating_value is None:
                        for tag in item.find_all(lambda tag: tag.has_attr('class')):
                            for class_name in tag.get('class'):
                                rating_match = re.search(r'rating(\d)', class_name)
                                if rating_match:
                                    rating_value = int(rating_match.group(1))
                                    break
                            if rating_value is not None:
                                break
                                
                    # Final fallback - look for allstar rating pattern
                    if rating_value is None:
                        allstar_elems = item.select("[class*='allstar']")
                        for elem in allstar_elems:
                            class_list = elem.get("class", [])
                            for class_name in class_list:
                                if "allstar" in class_name:
                                    # Patterns like "allstar50" for 5 stars, "allstar40" for 4 stars, etc.
                                    match = re.search(r'allstar(\d+)', class_name)
                                    if match:
                                        star_value = int(match.group(1))
                                        # Convert from 10-50 scale to 1-5
                                        rating_value = star_value // 10
                                        break
                    
                    # Accept movies without ratings (marks/wishes) if specified
                    if rating_value is None:
                        print(f"No rating: {title}")
                        # Create placeholder rating of 0 to indicate no rating
                        rating_value = 0
                    
                    # Extract info text for year extraction
                    info_elem = None
                    for info_selector in [".intro", ".pub", ".abstract", ".info .pl", ".info span", ".meta"]:
                        info_elem = item.select_one(info_selector)
                        if info_elem:
                            break
                    info_text = info_elem.text.strip() if info_elem else ""
                    
                    # Extract the year (preferably US year)
                    year = extract_us_year(info_text)
                    
                    # Extract English title if available
                    english_title = None
                    if " / " in title:
                        title_parts = title.split(" / ")
                        # Usually the second part is the English title if it contains English letters
                        for part in title_parts[1:]:
                            if re.search(r'[a-zA-Z]', part):
                                english_title = part.strip()
                                break
                    
                    # Create movie data with essential information
                    movie_data = {
                        "title": title,
                        "douban_id": douban_id,
                        "douban_url": douban_url,
                        "rating": rating_value,
                        "year": year
                    }
                    
                    if english_title:
                        movie_data["english_title"] = english_title
                    
                    # Include additional details if requested
                    if include_details:
                        movie_data["info"] = info_text
                    
                    # Process sequentially for IMDb extraction
                    if not skip_imdb and imdb_extraction_failures < max_imdb_failures:
                        print(f"Movie: {title} ({year}) - {rating_value}★")
                        
                        # Insert minimal delay before fetching movie details
                        if THROTTLING_ENABLED:
                            delay = random.uniform(MIN_MOVIE_DELAY, MAX_MOVIE_DELAY)
                            print(f"Waiting {delay:.1f}s...")
                            time.sleep(delay)
                        
                        # Try up to 2 times maximum (reduced from 3) for each movie if extraction fails
                        imdb_id = None
                        for attempt in range(2):  # Reduced from 3 to 2
                            try:
                                # Pass the title, year and english_title to the extraction function
                                imdb_id = extract_imdb_id(browser, douban_url, title, year, english_title)
                                    
                                if imdb_id:
                                    # Reset failure counter on success and increment success counter
                                    imdb_extraction_failures = max(0, imdb_extraction_failures - 1)
                                    imdb_extraction_success += 1
                                    break
                                
                                # Only retry if the first attempt fails and we don't have too many failures
                                if attempt < 1 and imdb_extraction_failures < max_imdb_failures - 1:
                                    print(f"  - Retrying...")
                                    # Very brief delay
                                    time.sleep(0.2)
                                
                            except Exception as e:
                                if attempt == 1:  # Only increment failures after all attempts
                                    imdb_extraction_failures += 1
                        
                        if imdb_id:
                            movie_data["imdb_id"] = imdb_id
                            print(f"  - IMDb ID: {imdb_id} ✓")
                        else:
                            imdb_extraction_failures += 1
                            print(f"  - IMDb ID: Not found ✗")
                                
                            # If too many consecutive failures, disable IMDb extraction temporarily
                            if imdb_extraction_failures >= max_imdb_failures:
                                print(f"\nToo many extraction failures ({max_imdb_failures}). Pausing extraction.")
                                print(f"Successes so far: {imdb_extraction_success}")
                                
                                # Take a minimal break
                                time.sleep(3) # Much shorter break
                                
                                # Reset counters to give it another try after the break
                                imdb_extraction_failures = max_imdb_failures // 2
                    else:
                        print(f"Added: {title} ({year}) - {rating_value}★")
                    
                    # Add to ratings list
                    ratings.append(movie_data)
                    items_processed += 1
                    
                    # Only pause between movies if throttling is enabled
                    if THROTTLING_ENABLED and not skip_imdb and imdb_extraction_failures < max_imdb_failures:
                        time.sleep(random.uniform(0.5, 1.5))
                    
                except Exception as e:
                    # Log important errors
                    print(f"Error processing movie: {str(e)[:100]}")
                    continue
            
            # Save ratings incrementally - less frequently for speed
            if items_processed % 30 == 0 or items_processed > 0:  # Changed from 15 to 30
                print(f"Saving {len(ratings)} ratings...")
                save_json(ratings, DOUBAN_EXPORT_PATH)
            
            # Check for next page with multiple strategies
            has_next_page = False
            
            # Strategy 1: Check pagination element for next link
            if pagination:
                next_link = pagination.select_one(".next a")
                if next_link:
                    has_next_page = True
                    
                # If we don't find next link specifically, check if we're on the last page
                elif not pagination.select_one(".next.disable-link") and not pagination.select_one(".disable-link"):
                    # Get all page numbers in the pagination
                    page_links = pagination.select("a[href]")
                    page_numbers = [int(link.text.strip()) for link in page_links if link.text.strip().isdigit()]
                    
                    if page_numbers:
                        max_visible_page = max(page_numbers)
                        if page < max_visible_page:
                            has_next_page = True
                            print(f"Current page {page} is less than max visible page {max_visible_page}")
            else:
                # If no pagination is found but we have movies, assume there might be more
                if movie_items and consecutive_empty_pages == 0:
                    has_next_page = True
                    print("No pagination found but movies exist. Trying next page.")
                
            # Strategy 2: Check if we've reached the manually specified max pages
            if manual_max_pages and page >= start_page + manual_max_pages - 1:
                has_next_page = False
                print("Reached manually specified maximum page.")
            
            # If we have a non-empty page but couldn't determine next page status, continue anyway
            if movie_items and not has_next_page and consecutive_empty_pages == 0:
                # Only do this for a reasonable number of attempts
                if page < 200:  # Safety limit
                    has_next_page = True
                    print("Forcing next page check despite pagination indicators.")
            
            # Increment page counter and update progress bar
            page += 1
            pbar.update(1)
            
            # Only pause between pages if throttling is enabled
            if THROTTLING_ENABLED:
                delay = random.uniform(0.5, 1.0)
                print(f"Waiting {delay:.1f}s before next page...")
                time.sleep(delay)
            
            # Save ratings less frequently
            if page % 3 == 0:  # Only save every 3 pages
                print(f"Saving {len(ratings)} ratings collected so far...")
                save_json(ratings, DOUBAN_EXPORT_PATH)
        
        pbar.close()
        
        # Final stats
        movies_with_imdb = sum(1 for r in ratings if r.get('imdb_id'))
        if len(ratings) > 0:
            print(f"\nIMDb Stats: {movies_with_imdb}/{len(ratings)} movies have IMDb IDs ({movies_with_imdb/len(ratings)*100:.1f}%)")
        else:
            print("\nNo ratings found. Please check your Douban account and privacy settings.")
        
        return ratings
    finally:
        # Save one final time
        if ratings:
            save_json(ratings, DOUBAN_EXPORT_PATH)

def check_for_detection(browser):
    """Check if Douban has detected automated access."""
    try:
        # Look for error messages in the page
        detection_phrases = [
            "有异常请求从你的 IP 发出",  # Abnormal requests from your IP
            "机器人",                    # Robot/bot
            "验证码",                    # Verification code
            "异常请求",                  # Abnormal request
            "请求频率",                  # Request frequency
            "访问频率",                  # Access frequency
            "访问异常",                  # Abnormal access
            "blocked",
            "unusual activity"
        ]
        
        page_text = browser.page_source
        for phrase in detection_phrases:
            if phrase in page_text:
                # Save a screenshot of the detection page
                timestamp = int(time.time())
                os.makedirs("../debug_logs/screenshots", exist_ok=True)
                
                screenshot_path = os.path.join("../debug_logs/screenshots", f"detection_{timestamp}.png")
                browser.save_screenshot(screenshot_path)
                
                # Save the HTML content
                html_path = os.path.join("debug_logs", f"detection_{timestamp}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(page_text)
                
                logger.warning(f"Detection phrase found: '{phrase}'. Screenshot saved to {screenshot_path}")
                
                # If it's a verification code/captcha page, still allow manual resolution
                if "验证码" in page_text or "captcha" in page_text.lower():
                    # Ask user if they want to solve the captcha or continue
                    if input("\nCaptcha detected. Solve it manually? (y/n, default: y): ").lower() != 'n':
                        handle_captcha(browser)
                        return False  # Captcha solved, no longer detected
                
                return True
        
        # Also check for verification/captcha images
        captcha_selectors = [
            "img[src*='captcha']", 
            "img[alt*='验证码']",
            ".captcha",
            "#captcha",
            "input[name*='captcha']"
        ]
        
        for selector in captcha_selectors:
            captcha_elements = browser.find_elements(By.CSS_SELECTOR, selector)
            if captcha_elements:
                logger.warning(f"Captcha element found: {selector}")
                
                # Ask user if they want to solve the captcha or continue
                if input("\nCaptcha detected. Solve it manually? (y/n, default: y): ").lower() != 'n':
                    handle_captcha(browser)
                    return False  # Captcha solved, no longer detected
                
                return True
        
        return False
    except Exception as e:
        logger.error(f"Error checking for detection: {e}")
        return False

def handle_captcha(browser):
    """Handle captcha/verification by prompting user for manual intervention."""
    try:
        # Save a screenshot for reference
        timestamp = int(time.time())
        os.makedirs("../debug_logs/screenshots", exist_ok=True)
        
        screenshot_path = os.path.join("../debug_logs/screenshots", f"captcha_{timestamp}.png")
        browser.save_screenshot(screenshot_path)
        
        print("\n" + "="*60)
        print("⚠️  CAPTCHA DETECTED - MANUAL INTERVENTION REQUIRED  ⚠️")
        print("="*60)
        print(f"A screenshot has been saved to: {screenshot_path}")
        print("\nPlease follow these steps:")
        print("1. Look at the browser window")
        print("2. Complete the captcha or verification")
        print("3. Make sure you can see the page content after verification")
        
        # Wait for user to complete the captcha
        input("\nPress Enter AFTER you have completed the verification...")
        
        # Ask the user if they succeeded
        confirmation = input("Were you able to successfully complete the verification? (y/n): ").lower()
        if confirmation in ['y', 'yes']:
            print("Verification confirmed. Continuing...")
            # Take a longer break after verification to avoid immediate re-detection
            time.sleep(random.uniform(5, 10))
            return True
        else:
            print("Verification not completed. Taking a longer break...")
            # Take an extended break if verification failed
            time.sleep(random.uniform(60, 120))
            return False
            
    except Exception as e:
        logger.error(f"Error handling captcha: {e}")
        # Still take a break if there was an error
        time.sleep(30)
        return False

def add_human_browsing_behavior(browser):
    """Add random human-like browsing behavior to appear more natural."""
    try:
        # Only add this behavior sometimes
        if random.random() < 0.3:  # 30% chance
            # Random scrolling
            scroll_amount = random.randint(100, 500)
            browser.execute_script(f"window.scrollBy(0, {scroll_amount})")
            time.sleep(random.uniform(0.5, 1.5))
            
            # Sometimes scroll back up
            if random.random() < 0.3:
                browser.execute_script(f"window.scrollBy(0, -{scroll_amount//2})")
                time.sleep(random.uniform(0.3, 0.8))
            
            # Sometimes jiggle the mouse (simulated via JS)
            if random.random() < 0.2:
                browser.execute_script("""
                    var event = new MouseEvent('mousemove', {
                        'view': window,
                        'bubbles': true,
                        'cancelable': true,
                        'clientX': Math.random() * window.innerWidth,
                        'clientY': Math.random() * window.innerHeight
                    });
                    document.dispatchEvent(event);
                """)
    except Exception as e:
        # Ignore any errors in the human behavior simulation
        logger.debug(f"Error simulating human behavior: {e}")
        pass

# JavaScript function for extracting IMDb IDs (used in extract_imdb_id)
js_script = """
    try {
        // Check for direct IMDb links in the page
        const imdbLinks = document.querySelectorAll('a[href*="imdb.com/title/"]');
        for (const link of imdbLinks) {
            const href = link.getAttribute('href');
            const match = href.match(/title\\/(tt\\d+)/);
            if (match) return match[1];
        }
        
        // Check for IMDb ID in the info section
        const infoSection = document.getElementById('info');
        if (infoSection) {
            const infoText = infoSection.textContent;
            
            // Look for standard IMDb label pattern
            const labelMatch = infoText.match(/IMDb[：:]\\s*(?:[^\\n]*?)(tt\\d{7,10})/i);
            if (labelMatch) return labelMatch[1];
            
            // Look for any IMDb ID pattern in info
            const idMatch = infoText.match(/\\b(tt\\d{7,10})\\b/);
            if (idMatch) return idMatch[1];
        }
        
        // Check modern Douban layout
        const subjectInfo = document.querySelector('.subject-info');
        if (subjectInfo) {
            const subjectText = subjectInfo.textContent;
            const labelMatch = subjectText.match(/IMDb[：:]\\s*(?:[^\\n]*?)(tt\\d{7,10})/i);
            if (labelMatch) return labelMatch[1];
            
            const idMatch = subjectText.match(/\\b(tt\\d{7,10})\\b/);
            if (idMatch) return idMatch[1];
        }
        
        // Look for any IMDb ID anywhere in the page (last resort)
        const pageText = document.body.textContent;
        const pageMatch = pageText.match(/IMDb[：:]\\s*(?:[^\\n]*?)(tt\\d{7,10})/i);
        if (pageMatch) return pageMatch[1];
        
        // Just find any IMDb ID in the page content
        const rawMatch = pageText.match(/\\b(tt\\d{7,10})\\b/);
        if (rawMatch) return rawMatch[1];
        
        return null;
    } catch (e) {
        console.error("Error extracting IMDb ID:", e);
        return null;
    }
"""

def fill_missing_imdb_ids(browser=None, close_browser=True, offline_only=False):
    """
    Process movies without IMDb IDs by:
    1. First checking debug logs to find saved HTML files
    2. If not found in logs and offline_only=False, using the Douban URL to try again
    
    Args:
        browser: Optional existing browser instance. If None, a new one will be created.
        close_browser: Whether to close the browser when done (if we created it)
        offline_only: If True, only process saved HTML files without online lookups
    """
    try:
        print("\n===== FILLING MISSING IMDB IDs =====")
        
        # Check if ratings file exists
        if not os.path.exists(DOUBAN_EXPORT_PATH):
            print(f"Error: Ratings file not found at {DOUBAN_EXPORT_PATH}")
            return False
            
        # Load existing ratings
        with open(DOUBAN_EXPORT_PATH, 'r', encoding='utf-8') as f:
            ratings = json.load(f)
            
        # Find movies without IMDb IDs
        missing_imdb_count = 0
        movies_without_imdb = []
        
        for movie in ratings:
            if 'imdb_id' not in movie or not movie['imdb_id']:
                missing_imdb_count += 1
                movies_without_imdb.append(movie)
                
        if missing_imdb_count == 0:
            print("No movies missing IMDb IDs. Nothing to do.")
            return True
            
        print(f"Found {missing_imdb_count} movies without IMDb IDs.")
        
        # Create browser if needed and not in offline-only mode
        should_close_browser = False
        browser_created = False
        if browser is None and not offline_only:
            print("Setting up browser for IMDb extraction...")
            browser = setup_browser(headless=True)
            browser_created = True
            should_close_browser = close_browser
        elif offline_only:
            print("Operating in offline-only mode - skipping browser initialization")
            browser = None
        
        # Setup tracking variables
        found_in_logs = 0
        found_via_douban = 0
        still_missing = 0
        fixed_count = 0
        
        # Create progress bar
        pbar = tqdm(total=missing_imdb_count, desc="Processing", unit="movie")
        
        # Process each movie without IMDb ID
        for movie in movies_without_imdb:
            douban_id = movie.get('douban_id')
            title = movie.get('title', '').strip()
            year = movie.get('year')
            english_title = movie.get('english_title')
            
            # Skip if no douban_id (shouldn't happen)
            if not douban_id:
                pbar.update(1)
                continue
                
            print(f"\nProcessing: {title} ({douban_id})")
            imdb_id = None
            
            # Step 1: Check for HTML files in detection_pages that match this Douban ID
            detection_pages_dir = "debug_logs/detection_pages"
            if os.path.exists(detection_pages_dir):
                detection_files = [f for f in os.listdir(detection_pages_dir) 
                                  if f.startswith(f"detection_{douban_id}_")]
                
                if detection_files:
                    print(f"Found {len(detection_files)} detection page(s) for this movie")
                    
                    # Try to extract IMDb ID from each detection file
                    for detection_file in detection_files:
                        file_path = os.path.join(detection_pages_dir, detection_file)
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            html_content = f.read()
                            
                        # Try to extract IMDb ID from the HTML
                        extracted_id = extract_imdb_id_from_html(html_content)
                        if extracted_id:
                            imdb_id = extracted_id
                            found_in_logs += 1
                            print(f"Found IMDb ID in detection logs: {imdb_id}")
                            break
            
            # Step 2: Check for HTML files in movie_pages that match this Douban ID
            if not imdb_id:
                movie_pages_dir = "debug_logs/movie_pages"
                if os.path.exists(movie_pages_dir):
                    movie_files = [f for f in os.listdir(movie_pages_dir) 
                                  if f"_{douban_id}_" in f]
                    
                    if movie_files:
                        print(f"Found {len(movie_files)} movie page(s) for this movie")
                        
                        # Try to extract IMDb ID from each movie file
                        for movie_file in movie_files:
                            file_path = os.path.join(movie_pages_dir, movie_file)
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                html_content = f.read()
                                
                            # Try to extract IMDb ID from the HTML
                            extracted_id = extract_imdb_id_from_html(html_content)
                            if extracted_id:
                                imdb_id = extracted_id
                                found_in_logs += 1
                                print(f"Found IMDb ID in movie logs: {imdb_id}")
                                break
            
            # Step 3: If not found in logs and not in offline-only mode, try directly from Douban
            if not imdb_id and browser and not offline_only:
                print("Trying to get IMDb ID directly from Douban...")
                douban_url = movie.get('douban_url')
                
                if not douban_url:
                    # Construct URL if missing
                    douban_url = f"https://movie.douban.com/subject/{douban_id}/"
                
                # Try to extract IMDb ID from Douban
                extracted_id = extract_imdb_id(browser, douban_url, title, year, english_title)
                
                if extracted_id:
                    imdb_id = extracted_id
                    found_via_douban += 1
                    print(f"Found IMDb ID via Douban: {imdb_id}")
                else:
                    # If not found on Douban, try IMDb search as a last resort
                    print("Trying IMDb search...")
                    search_id = search_imdb_for_movie(browser, title, year, english_title)
                    if search_id:
                        imdb_id = search_id
                        found_via_douban += 1
                        print(f"Found IMDb ID via search: {imdb_id}")
            elif offline_only and not imdb_id:
                print("Skipping online lookups (offline-only mode)")
            
            # Update the movie with IMDb ID if found
            if imdb_id:
                for i, r in enumerate(ratings):
                    if r.get('douban_id') == douban_id:
                        ratings[i]['imdb_id'] = imdb_id
                        fixed_count += 1
                        # Save incremental progress every 10 movies
                        if fixed_count % 10 == 0:
                            save_json(ratings, DOUBAN_EXPORT_PATH)
                            print(f"Saved progress ({fixed_count}/{missing_imdb_count} fixed)")
                        break
            else:
                still_missing += 1
                print("IMDb ID not found.")
            
            # Add a small delay only if we're not in offline mode
            if not offline_only:
                time.sleep(random.uniform(0.5, 1.0))
            pbar.update(1)
        
        pbar.close()
        
        # Save the final results
        save_json(ratings, DOUBAN_EXPORT_PATH)
        
        # Print final statistics
        print("\n===== RESULTS =====")
        print(f"Total movies processed: {missing_imdb_count}")
        print(f"Found in debug logs: {found_in_logs}")
        if not offline_only:
            print(f"Found via Douban/IMDb: {found_via_douban}")
        print(f"Total IMDb IDs added: {fixed_count}")
        print(f"Still missing: {still_missing}")
        
        # Calculate new percentage
        total_movies = len(ratings)
        movies_with_imdb = sum(1 for r in ratings if r.get('imdb_id'))
        print(f"\nUpdated IMDb Stats: {movies_with_imdb}/{total_movies} movies have IMDb IDs ({movies_with_imdb/total_movies*100:.1f}%)")
        
        return True
        
    except Exception as e:
        logger.error(f"Error filling missing IMDb IDs: {e}")
        print(f"Error: {str(e)}")
        return False
    finally:
        # Close the browser if we created it
        if browser and browser_created and should_close_browser:
            try:
                browser.quit()
            except:
                pass

def export_douban_ratings():
    """Main function to export Douban ratings with manual assistance."""
    ensure_data_dir()
    
    # Create necessary directories
    os.makedirs(DETECTION_PAGES_DIR, exist_ok=True)
    os.makedirs("debug_logs", exist_ok=True)
    
    browser = None
    try:
        print("\n===== DOUBAN RATING EXPORT =====")
        print("This script will help you export your Douban movie ratings.")
        print("You'll need to log in manually and provide your Douban user ID.")
        
        # Ask whether to include detailed information
        include_details = input("\nInclude detailed info in output? (y/n, default: n): ").lower() == 'y'
        
        # Ask about fast mode
        global FAST_MODE
        fast_mode = input("\nEnable fast mode? (Less logging, fewer file saves, faster performance) (y/n, default: y): ").lower() != 'n'
        FAST_MODE = fast_mode
        if FAST_MODE:
            print("Fast mode enabled. Most debug information will be skipped for better performance.")
        else:
            print("Fast mode disabled. Will save debug information for better troubleshooting.")
        
        # Ask about slow mode for more stable loading
        global SLOW_MODE, PAGE_LOAD_TIMEOUT
        slow_mode = input("\nEnable slow mode? (More stable loading for large collections) (y/n, default: n): ").lower() == 'y'
        SLOW_MODE = slow_mode
        if SLOW_MODE:
            print("Slow mode enabled. Pages will load more slowly but with better stability.")
            # Ask for custom timeout
            timeout = input(f"Page load timeout in seconds (default: {PAGE_LOAD_TIMEOUT}): ")
            if timeout and timeout.isdigit():
                PAGE_LOAD_TIMEOUT = int(timeout)
                print(f"Page load timeout set to {PAGE_LOAD_TIMEOUT} seconds")
        
        # Ask whether to enable throttling - now defaults to disabled
        throttling_enabled = input("\nEnable throttling? (Slower but less likely to be detected) (y/n, default: n): ").lower() == 'y'
        global THROTTLING_ENABLED
        THROTTLING_ENABLED = throttling_enabled
        if THROTTLING_ENABLED:
            print("Throttling enabled. The script will run slower but with less chance of detection.")
            
            # Additional throttling options
            min_page_delay = input("Minimum seconds between page requests (default: 3.0): ")
            if min_page_delay and min_page_delay.replace('.', '', 1).isdigit():
                global MIN_PAGE_DELAY
                MIN_PAGE_DELAY = float(min_page_delay)
            
            max_page_delay = input("Maximum seconds between page requests (default: 7.0): ")
            if max_page_delay and max_page_delay.replace('.', '', 1).isdigit():
                global MAX_PAGE_DELAY
                MAX_PAGE_DELAY = float(max_page_delay)
        else:
            print("Throttling disabled. The script will run at maximum speed.")
        
        # Create parameters for backward compatibility
        use_efficient_mode = False
        max_workers = 1
            
        # Ask whether to skip IMDb extraction
        skip_imdb = input("\nSkip IMDb ID extraction entirely? (y/n, default: n): ").lower() == 'y'
        if skip_imdb:
            print("IMDb ID extraction will be skipped.")
        else:
            print("IMDb IDs will be extracted when possible.")
        
        # Option to run in headless mode from the start
        headless_mode = input("\nUse headless browser? (More stable but requires no visual interaction) (y/n, default: n): ").lower() == 'y'
        if headless_mode:
            print("Using headless browser mode.")
        
        # Warn about large collections
        print("\n===== LARGE COLLECTIONS =====")
        print("If you have a large collection (140+ pages), you may want to process it in batches.")
        print("You can specify a page range when prompted during execution.")
        print("This can help avoid detection and make the process more manageable.")
            
        # Simplified detection-handling information
        print("\n===== DETECTION HANDLING =====")
        print("If Douban detects automated access, the script will:")
        print("1. Save the HTML for later processing")
        print("2. Skip the current item and continue to the next one")
        
        # Timeout handling information
        print("\n===== TIMEOUT HANDLING =====")
        print(f"Page load timeout: {PAGE_LOAD_TIMEOUT} seconds")
        print(f"Max retries per page: {MAX_PAGE_RETRIES}")
        print("If a page fails to load after all retries, the script will:")
        print("1. Save any HTML content for debugging")
        print("2. Skip to the next page and continue processing")
        
        input("\nPress Enter to continue...")
        
        # Set up browser with stability measures
        print("\nInitializing browser...")
        try:
            browser = setup_browser(headless=headless_mode)
            print("Browser initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize browser: {e}")
            print("You can try the following:")
            print("1. Update Chrome to the latest version")
            print("2. Try running in headless mode")
            print("3. Restart your computer and try again")
            return False
        
        # Manual login - adjusted for headless mode
        if headless_mode:
            print("\n=== HEADLESS MODE - SPECIAL LOGIN PROCEDURE ===")
            print("Since we're running in headless mode, manual login must be done differently.")
            print("1. We'll first launch a temporary visible browser for you to log in")
            print("2. Then we'll capture cookies from that browser")
            print("3. Finally, we'll apply those cookies to our headless browser")
            
            if input("Proceed with special login procedure? (y/n): ").lower() in ['y', 'yes']:
                # Create a temporary visible browser for login
                print("Launching visible browser for login...")
                temp_options = Options()
                temp_browser = webdriver.Chrome(options=temp_options)
                
                if login_to_douban_manually(temp_browser):
                    print("Login successful! Transferring cookies to headless browser...")
                    # Get cookies from temp browser
                    cookies = temp_browser.get_cookies()
                    
                    # Navigate to douban in the headless browser
                    browser.get("https://www.douban.com")
                    
                    # Apply cookies to headless browser
                    for cookie in cookies:
                        browser.add_cookie(cookie)
                    
                    # Close temp browser
                    temp_browser.quit()
                    
                    # Test if login was transferred successfully
                    browser.get("https://www.douban.com")
                    time.sleep(2)
                    if "登录" not in browser.page_source:
                        print("Cookie transfer successful!")
                    else:
                        print("Cookie transfer failed. Please run without headless mode.")
                        return False
                else:
                    temp_browser.quit()
                    print("Login failed. Please run without headless mode.")
                    return False
            else:
                print("Login procedure cancelled. Please run without headless mode.")
                return False
        else:
            # Regular login for non-headless mode
            if not login_to_douban_manually(browser):
                print("Login failed or was not confirmed. Exiting.")
                return False
        
        # Get user ID with manual assistance
        user_id = get_user_id_manually(browser)
        
        if not user_id:
            print("No user ID provided. Exiting.")
            return False
        
        # Add an option to verify the first page loads correctly
        if input("\nTest loading the first page before proceeding? (y/n, default: y): ").lower() != 'n':
            print("\nTesting page loading...")
            test_url = f"https://movie.douban.com/people/{user_id}/collect?start=0&sort=time&rating=all&filter=all&mode=grid"
            
            try:
                browser.get(test_url)
                print("Page loaded successfully! Press Enter to continue...")
                input()
            except TimeoutException:
                print("\n⚠️ Page load timed out. This could indicate connectivity issues.")
                print("Options:")
                print("1. Increase page load timeout")
                print("2. Enable slow mode for more stable loading")
                print("3. Continue anyway (page loading will be retried during processing)")
                
                if input("\nContinue anyway? (y/n, default: n): ").lower() != 'y':
                    return False
            except Exception as e:
                print(f"\n⚠️ Error loading test page: {e}")
                if input("\nContinue anyway? (y/n, default: n): ").lower() != 'y':
                    return False
        
        print(f"\nFetching ratings for Douban user: {user_id}")
        ratings = fetch_movie_ratings(
            browser, 
            user_id, 
            include_details, 
            use_efficient_mode, 
            skip_imdb,
            max_workers
        )
        
        print(f"\nFound {len(ratings)} rated movies on Douban")
        
        if len(ratings) == 0:
            print("\n⚠️ WARNING: No ratings were found!")
            return False
            
        # Check how many movies have IMDb IDs
        movies_with_imdb = sum(1 for r in ratings if r.get('imdb_id'))
        if not skip_imdb and movies_with_imdb < len(ratings):
            print(f"\n⚠️ NOTE: Only {movies_with_imdb}/{len(ratings)} movies have IMDb IDs.")
            
            # Ask if user wants to fill missing IMDb IDs now
            if input("\nWould you like to attempt to fill missing IMDb IDs from debug logs and by retrying? (y/n, default: y): ").lower() != 'n':
                # Keep the browser open and pass it to the fill_missing_imdb_ids function
                print("\nAttempting to fill missing IMDb IDs...")
                fill_missing_imdb_ids(browser=browser, close_browser=False)
            
        # Save ratings to file (final save)
        save_json(ratings, DOUBAN_EXPORT_PATH)
        
        print(f"Successfully exported Douban ratings to {DOUBAN_EXPORT_PATH}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting Douban ratings: {e}")
        print(f"Error: {str(e)}")
        return False
        
    finally:
        if browser:
            try:
                browser.quit()
            except Exception as e:
                print(f"Error closing browser: {e}")

def deep_search_imdb_ids(limit=None):
    """
    Deep search for IMDb IDs using multiple search engines and techniques.
    This is a last resort for finding IDs that couldn't be found through other methods.
    
    Args:
        limit: Maximum number of movies to process (None for all)
    """
    try:
        print("\n===== DEEP SEARCH FOR IMDB IDs =====")
        
        # Check if ratings file exists
        if not os.path.exists(DOUBAN_EXPORT_PATH):
            print(f"Error: Ratings file not found at {DOUBAN_EXPORT_PATH}")
            return False
            
        # Load existing ratings
        with open(DOUBAN_EXPORT_PATH, 'r', encoding='utf-8') as f:
            ratings = json.load(f)
            
        # Find movies without IMDb IDs
        movies_without_imdb = []
        
        for movie in ratings:
            if 'imdb_id' not in movie or not movie['imdb_id']:
                movies_without_imdb.append(movie)
                
        missing_imdb_count = len(movies_without_imdb)
        if missing_imdb_count == 0:
            print("No movies missing IMDb IDs. Nothing to do.")
            return True
            
        print(f"Found {missing_imdb_count} movies without IMDb IDs.")
        
        # Limit the number of movies to process if specified
        if limit and limit < missing_imdb_count:
            print(f"Processing only {limit} movies as requested.")
            movies_to_process = movies_without_imdb[:limit]
        else:
            movies_to_process = movies_without_imdb
            
        # Set up browser with headless mode for fast processing
        print("Setting up browser for deep search...")
        browser = setup_browser(headless=True)
        
        # Setup tracking variables
        found_count = 0
        fixed_count = 0
        
        # Create progress bar
        pbar = tqdm(total=len(movies_to_process), desc="Deep searching", unit="movie")
        
        # Process each movie without IMDb ID
        for movie_idx, movie in enumerate(movies_to_process):
            douban_id = movie.get('douban_id')
            title = movie.get('title', '').strip()
            year = movie.get('year')
            english_title = movie.get('english_title')
            
            # Skip if no douban_id (shouldn't happen)
            if not douban_id:
                pbar.update(1)
                continue
                
            print(f"\nDeep searching [{movie_idx+1}/{len(movies_to_process)}]: {title} ({douban_id})")
            imdb_id = None
            
            # Extract the main title (before first slash if present)
            main_title = title.split('/')[0].strip() if '/' in title else title
            
            # Extract English title from the title field if not already present
            if not english_title and '/' in title:
                # Look for parts after the first slash that contain English letters
                for part in title.split('/')[1:]:
                    cleaned_part = part.strip()
                    if re.search(r'[a-zA-Z]', cleaned_part):
                        english_title = cleaned_part
                        break
            
            # ATTEMPT 1: Try direct IMDb search
            try:
                if english_title:
                    search_title = english_title
                else:
                    search_title = main_title
                    
                if year:
                    search_query = f"{search_title} {year} movie"
                else:
                    search_query = f"{search_title} movie"
                    
                print(f"Searching IMDb for: {search_query}")
                search_result = search_imdb_for_movie(browser, search_title, year, english_title)
                
                if search_result:
                    imdb_id = search_result
                    found_count += 1
                    print(f"Found IMDb ID via direct search: {imdb_id}")
            except Exception as e:
                print(f"Error in direct IMDb search: {str(e)[:100]}")
            
            # ATTEMPT 2: If not found, try to use a Google search to find IMDb
            if not imdb_id:
                try:
                    # Construct a Google search query specifically targeting IMDb
                    if english_title and year:
                        google_query = f"{english_title} {year} site:imdb.com"
                    elif english_title:
                        google_query = f"{english_title} site:imdb.com"
                    elif year:
                        google_query = f"{main_title} {year} site:imdb.com"
                    else:
                        google_query = f"{main_title} site:imdb.com"
                        
                    print(f"Trying Google search: {google_query}")
                    # Navigate to Google and perform search
                    search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(google_query)}"
                    
                    try:
                        browser.set_page_load_timeout(10)
                        browser.get(search_url)
                    except TimeoutException:
                        print("Google search timed out, but attempting extraction anyway...")
                    except Exception as e:
                        print(f"Error accessing Google: {str(e)[:100]}")
                        
                    # Extract IMDb links from the search results
                    soup = BeautifulSoup(browser.page_source, 'html.parser')
                    for a in soup.select('a[href*="imdb.com/title/"]'):
                        href = a.get('href', '')
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb_id = imdb_match.group(1)
                            found_count += 1
                            print(f"Found IMDb ID via Google search: {imdb_id}")
                            break
                except Exception as e:
                    print(f"Error in Google search: {str(e)[:100]}")
            
            # ATTEMPT 3: Try another search engine if Google didn't work
            if not imdb_id:
                try:
                    # Construct a Bing search query
                    if english_title and year:
                        bing_query = f"{english_title} {year} IMDb"
                    elif english_title:
                        bing_query = f"{english_title} IMDb"
                    elif year:
                        bing_query = f"{main_title} {year} IMDb"
                    else:
                        bing_query = f"{main_title} IMDb"
                    
                    print(f"Trying Bing search: {bing_query}")
                    search_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(bing_query)}"
                    
                    try:
                        browser.set_page_load_timeout(10)
                        browser.get(search_url)
                    except TimeoutException:
                        print("Bing search timed out, but attempting extraction anyway...")
                    except Exception as e:
                        print(f"Error accessing Bing: {str(e)[:100]}")
                    
                    # Extract IMDb links from the search results
                    soup = BeautifulSoup(browser.page_source, 'html.parser')
                    for a in soup.select('a[href*="imdb.com/title/"]'):
                        href = a.get('href', '')
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb_id = imdb_match.group(1)
                            found_count += 1
                            print(f"Found IMDb ID via Bing search: {imdb_id}")
                            break
                except Exception as e:
                    print(f"Error in Bing search: {str(e)[:100]}")
            
            # Update the movie with IMDb ID if found
            if imdb_id:
                for i, r in enumerate(ratings):
                    if r.get('douban_id') == douban_id:
                        ratings[i]['imdb_id'] = imdb_id
                        fixed_count += 1
                        
                        # Save incremental progress every 5 movies
                        if fixed_count % 5 == 0:
                            save_json(ratings, DOUBAN_EXPORT_PATH)
                            print(f"Saved progress ({fixed_count}/{len(movies_to_process)} fixed)")
                        break
            else:
                print("IMDb ID not found after deep search")
            
            # A bit longer delay to avoid rate limiting
            time.sleep(random.uniform(0.8, 1.5))
            pbar.update(1)
        
        pbar.close()
        
        # Save the final results
        save_json(ratings, DOUBAN_EXPORT_PATH)
        
        # Print final statistics
        print("\n===== DEEP SEARCH RESULTS =====")
        print(f"Total movies processed: {len(movies_to_process)}")
        print(f"Total IMDb IDs found: {found_count}")
        print(f"Total records updated: {fixed_count}")
        
        # Calculate new percentage
        total_movies = len(ratings)
        movies_with_imdb = sum(1 for r in ratings if r.get('imdb_id'))
        print(f"\nUpdated IMDb Stats: {movies_with_imdb}/{total_movies} movies have IMDb IDs ({movies_with_imdb/total_movies*100:.1f}%)")
        
        return True
    except Exception as e:
        logger.error(f"Error in deep search: {e}")
        print(f"Error: {str(e)}")
        return False
    finally:
        try:
            if browser:
                browser.quit()
        except:
            pass

if __name__ == "__main__":
    # Check command line arguments
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == '--fill-missing-imdb':
            # Check for offline-only flag
            offline_only = '--offline-only' in sys.argv
            fill_missing_imdb_ids(offline_only=offline_only)
        elif sys.argv[1] == '--deep-search':
            # Parse limit argument if present
            limit = None
            if len(sys.argv) > 2 and sys.argv[2].isdigit():
                limit = int(sys.argv[2])
            deep_search_imdb_ids(limit=limit)
        else:
            export_douban_ratings()
    else:
        export_douban_ratings() 