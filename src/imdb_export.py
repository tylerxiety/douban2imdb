"""
Script to export IMDb ratings with manual login assistance.
"""
import os
import time
import re
import json
import logging
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
from datetime import datetime

from utils import ensure_data_dir, save_json, logger

# Load environment variables
load_dotenv()

# Initialize constants from environment variables or defaults
IMDB_EXPORT_PATH = os.getenv("IMDB_EXPORT_PATH", "data/imdb_ratings.json")
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
DRIVER_PATH = os.getenv("DRIVER_PATH", "") 
BROWSER_MAX_INIT_ATTEMPTS = int(os.getenv("BROWSER_MAX_INIT_ATTEMPTS", "3"))
HEADLESS_MODE = os.getenv("HEADLESS_MODE", "False").lower() == "true"
DEBUG_DIR = "../debug_logs"

# Ensure the debug directory exists
os.makedirs(DEBUG_DIR, exist_ok=True)

def get_debug_filepath(prefix, file_type="html"):
    """Generate a debug file path with timestamp.
    
    Args:
        prefix: The prefix for the filename
        file_type: The file type (html or png)
    
    Returns:
        The full file path
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if file_type == "png":
        # Create screenshots directory if it doesn't exist
        screenshots_dir = os.path.join(DEBUG_DIR, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        return os.path.join(screenshots_dir, f"{prefix}_{timestamp}.png")
    else:
        return os.path.join(DEBUG_DIR, f"{prefix}_{timestamp}.html")

def setup_browser(headless=False):
    """Set up and return a Selenium browser instance."""
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
    chrome_options.add_argument("--disk-cache-size=52428800")  # 50MB disk cache
    chrome_options.add_argument("--dns-prefetch-disable")  # Disable DNS prefetching
    chrome_options.add_argument("--blink-settings=imagesEnabled=true")  # Keep images enabled for IMDb UI
    
    # Memory management to reduce crashes
    chrome_options.add_argument("--js-flags=--max-old-space-size=4096")  # Increase JS memory limit
    chrome_options.add_argument("--disable-features=RendererCodeIntegrity")  # May improve stability
    
    # Add headless mode if requested
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")  # Use larger window size
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Add user agent to avoid detection
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    # Create browser directly
    browser = webdriver.Chrome(options=chrome_options)
    
    # Set a reasonable timeout - less aggressive to avoid timeout issues
    browser.set_page_load_timeout(60)  # Increased timeout
    
    # Set script timeout - for executeScript calls
    browser.set_script_timeout(60)  # Increased timeout
    
    logger.info("Browser set up with performance optimizations")
    return browser

def login_to_imdb_manually(browser):
    """Navigate to IMDb and assist with manual login."""
    print("\n=== MANUAL LOGIN REQUIRED ===")
    print("1. A browser window will open to the IMDb login page")
    print("2. Please log in manually with your IMDb/Amazon credentials")
    print("3. Make sure you're fully logged in before continuing")
    print("4. If you encounter a CAPTCHA, please solve it manually")
    print("NOTE: If the page seems stuck loading, you can still proceed once you've logged in successfully")
    
    try:
        # Navigate to IMDb login page
        try:
            browser.get("https://www.imdb.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.imdb.com%2Fregistration%2Fap-signin-handler%2Fimdb_us&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=imdb_us&openid.mode=checkid_setup&siteState=eyJvcGVuaWQuYXNzb2NfaGFuZGxlIjoiaW1kYl91cyIsInJlZGlyZWN0VG8iOiJodHRwczovL3d3dy5pbWRiLmNvbS8_cmVmXz1sb2dpbiJ9&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
        except TimeoutException:
            print("\nThe page timed out while loading, but you may still be able to log in.")
            print("If you can see the IMDb login page, please proceed with login.")
        except Exception as e:
            print(f"\nError loading IMDb login page: {e}")
            print("Please try again or check your internet connection.")
        
        # Wait for user to confirm login
        input("\nPress Enter AFTER you have successfully logged in to IMDb...")
        
        # Ask user to explicitly confirm login success
        confirmation = input("Did you successfully log in to IMDb? (y/n): ")
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

def safe_scroll(browser, distance=500):
    """Scroll the page safely, with error handling."""
    try:
        browser.execute_script(f"window.scrollBy(0, {distance});")
        time.sleep(0.5)  # Brief pause to allow rendering
        return True
    except Exception as e:
        print(f"Error during scroll: {e}")
        return False

def fetch_imdb_ratings(browser):
    """Fetch all movie ratings for the current user with manual assistance."""
    ratings = []
    page = 1
    has_next_page = True
    
    # Create progress bar
    pbar = tqdm(desc="Fetching IMDb ratings", unit="page")
    
    # Ask if user wants to process only a specific number of pages
    max_pages_input = input("\nLimit to specific number of pages? (Enter a number or leave blank for all pages): ").strip()
    max_pages = None
    if max_pages_input and max_pages_input.isdigit():
        max_pages = int(max_pages_input)
        print(f"Will process at most {max_pages} pages of ratings.")
    else:
        print("Will process all available pages of ratings.")
    
    # Check if we're using headless mode
    is_headless = "headless" in browser.capabilities.get("chrome", {}).get("chromedriverVersion", "").lower()
    
    # Detect if we're on the new IMDb interface
    try:
        current_url = browser.current_url
        is_new_interface = "/user/" in current_url
        print(f"Current URL: {current_url}")
        print(f"Detected {'new' if is_new_interface else 'classic'} IMDb interface")
    except:
        print("Could not determine interface type, assuming classic interface")
        is_new_interface = False
    
    # For debugging, save the initial page HTML
    try:
        debug_initial = get_debug_filepath("initial_page")
        with open(debug_initial, "w", encoding="utf-8") as f:
            f.write(browser.page_source)
            print(f"Saved initial page HTML to {debug_initial}")
    except Exception as e:
        print(f"Could not save debug HTML: {e}")
    
    # Initialize an empty set to track processed titles to avoid duplicates
    processed_titles = set()
    
    # For the new interface, we need a special approach
    if is_new_interface:
        # Define maximum retries and timeouts
        max_retries = 100  # Increased from 20 to 100 for large rating collections
        consecutive_empty_pages = 0
        max_consecutive_empty = 15  # Increased from 5 to 15 before giving up
        
        print("Starting IMDb ratings extraction...")
        
        # Initial scroll to load first batch of content
        print("Performing initial scrolls to load content...")
        for i in range(5):  # Do more initial scrolls
            browser.execute_script(f"window.scrollTo(0, {(i+1)*1000});")
            time.sleep(3.0)  # Increased pause from 1.5 to 3.0
        
        # Main extraction loop
        while has_next_page and (max_pages is None or page <= max_pages):
            print(f"\nProcessing batch {page}...")
            
            # Save a snapshot of the current page for debugging
            try:
                debug_batch = get_debug_filepath(f"batch_{page}")
                with open(debug_batch, "w", encoding="utf-8") as f:
                    f.write(browser.page_source)
                    print(f"Saved HTML snapshot to {debug_batch}")
            except Exception as e:
                print(f"Could not save debug HTML: {e}")
            
            # Try a more targeted approach for the new IMDb interface
            try:
                # First, try to find all rating items using the most specific selectors based on actual HTML structure
                movie_data = browser.execute_script("""
                    var results = [];
                    
                    // Debug function
                    function debug(msg) {
                        console.log("DEBUG: " + msg);
                        return msg;
                    }
                    
                    debug("Starting extraction using exact HTML structure from debug logs");
                    
                    // Look for title links with the specific aria-label pattern found in debug logs
                    var titleLinks = document.querySelectorAll('a[aria-label^="View title page for"]');
                    debug("Found " + titleLinks.length + " title links with View title page aria-label");
                    
                    // Process each title link
                    titleLinks.forEach(function(link, index) {
                        try {
                            // Get title from aria-label
                            var ariaLabel = link.getAttribute('aria-label');
                            var titleMatch = ariaLabel.match(/View title page for (.+)/);
                            var title = titleMatch ? titleMatch[1] : link.textContent.trim();
                            
                            // Get the parent container that holds all movie info
                            var container = link.closest('.sc-f30335b4-0, div[class*="list-item"]');
                            if (!container) {
                                container = link.parentNode;
                                while (container && !container.querySelector('span[class*="dli-title-metadata-item"]') && 
                                       container.tagName !== 'BODY') {
                                    container = container.parentNode;
                                }
                            }
                            
                            if (!container) {
                                debug("No container found for " + title);
                                return;
                            }
                            
                            // Get year - using the exact class from debug logs
                            var year = null;
                            var yearElements = container.querySelectorAll('span[class*="dli-title-metadata-item"]');
                            for (var i = 0; i < yearElements.length; i++) {
                                var text = yearElements[i].textContent.trim();
                                // Year is the first metadata item
                                if (/^(19|20)\\d{2}/.test(text)) {
                                    year = text.substring(0, 4); // Get only the year part, not any suffix
                                    break;
                                }
                            }
                            
                            // Get IMDb ID from link href
                            var href = link.getAttribute('href');
                            var imdbIdMatch = href.match(/\\/title\\/(tt\\d+)/);
                            var imdbId = imdbIdMatch ? imdbIdMatch[1] : null;
                            
                            // Find rating - look for button with aria-label="Your rating: X" which contains the user's rating
                            var rating = null;
                            var ratingButtons = container.querySelectorAll('button[aria-label^="Your rating:"]');
                            if (ratingButtons.length > 0) {
                                var ratingLabel = ratingButtons[0].getAttribute('aria-label');
                                var ratingMatch = ratingLabel.match(/Your rating:\\s*(\\d+)/);
                                if (ratingMatch && ratingMatch[1]) {
                                    rating = parseInt(ratingMatch[1]);
                                    debug("Found rating for " + title + ": " + rating + " from aria-label: " + ratingLabel);
                                }
                            }
                            
                            // Only add if we have ALL required data (title, year, imdbId, and rating must all be present)
                            if (title && imdbId && rating && year) {
                                results.push({
                                    title: title,
                                    imdb_url: href.startsWith('http') ? href : 'https://www.imdb.com' + href,
                                    imdb_id: imdbId,
                                    year: year,
                                    rating: rating
                                });
                                debug("Added " + title + " (" + year + ") with rating " + rating);
                            } else {
                                debug("Missing required data for " + title + 
                                      " - imdbId: " + (imdbId ? "YES" : "NO") + 
                                      ", rating: " + (rating ? rating : "NO") + 
                                      ", year: " + (year ? year : "NO"));
                            }
                        } catch (e) {
                            console.error("Error processing title: " + e);
                        }
                    });
                    
                    debug("Extraction complete. Found " + results.length + " movies with all required data");
                    return results;
                """)
                
                # Debug the data returned
                print(f"\nFound {len(movie_data) if isinstance(movie_data, list) else 'unknown'} movies with complete data")
                
                if isinstance(movie_data, list) and movie_data:
                    print("\nFirst few movies found:")
                    for i, movie in enumerate(movie_data[:3]):
                        print(f"  {i+1}. {movie.get('title', 'N/A')} ({movie.get('year', 'N/A')}) - Rating: {movie.get('rating', 'N/A')}/10")
                
                # Process the extracted data - no defaults or hardcoded values
                if isinstance(movie_data, list) and len(movie_data) > 0:
                    print(f"\nAdding {len(movie_data)} movies to collection")
                    
                    # Count newly added items
                    new_count = 0
                    for movie in movie_data:
                        try:
                            title = movie.get('title', '')
                            year = movie.get('year', '')
                            rating = movie.get('rating')
                            imdb_id = movie.get('imdb_id', '')
                            
                            # Skip if any required data is missing
                            if not title or not year or rating is None or not imdb_id:
                                print(f"Skipping incomplete movie data: {movie}")
                                continue
                            
                            title_year_key = f"{title}|{year}"
                            
                            if title_year_key not in processed_titles:
                                processed_titles.add(title_year_key)
                                ratings.append(movie)
                                new_count += 1
                                print(f"Added: {title} ({year}) - Rating: {rating}/10")
                            else:
                                print(f"Skipped duplicate: {title} ({year})")
                        except Exception as e:
                            print(f"Error processing movie: {e}")
                    
                    print(f"Added {new_count} new ratings (total now: {len(ratings)})")
                    
                    # Check if we found any new ratings in this batch
                    if new_count == 0:
                        consecutive_empty_pages += 1
                        print(f"No new ratings in this batch. Consecutive batches without new ratings: {consecutive_empty_pages}/{max_consecutive_empty}")
                    else:
                        # Reset counter if we found new ratings
                        consecutive_empty_pages = 0
                    
                    # Save ratings to file - this must succeed
                    try:
                        print("\nSaving ratings to file...")
                        with open(IMDB_EXPORT_PATH, 'w', encoding='utf-8') as f:
                            json.dump(ratings, f, ensure_ascii=False, indent=2)
                        print(f"Successfully saved {len(ratings)} ratings to {IMDB_EXPORT_PATH}")
                        
                        # Verify file was written correctly
                        if os.path.exists(IMDB_EXPORT_PATH):
                            file_size = os.path.getsize(IMDB_EXPORT_PATH)
                            print(f"File exists with size: {file_size} bytes")
                        else:
                            print(f"ERROR: File {IMDB_EXPORT_PATH} does not exist after save!")
                    except Exception as e:
                        print(f"Error during save: {e}")
                        # Try alternate location
                        try:
                            alt_path = "imdb_ratings_alternate.json"
                            with open(alt_path, 'w', encoding='utf-8') as f:
                                json.dump(ratings, f, ensure_ascii=False, indent=2)
                            print(f"Saved to alternate location: {alt_path}")
                        except Exception as e2:
                            print(f"Critical error - cannot save to any location: {e2}")
                else:
                    print("No movies with complete data found. Will try again on next batch.")
                    consecutive_empty_pages += 1
                    print(f"Consecutive batches without new ratings: {consecutive_empty_pages}/{max_consecutive_empty}")
            except Exception as e:
                print(f"Error extracting data: {e}")
                consecutive_empty_pages += 1
                print(f"Consecutive batches without new ratings: {consecutive_empty_pages}/{max_consecutive_empty}")
            
            # If we've had too many empty pages in a row, we might be at the end
            if consecutive_empty_pages >= max_consecutive_empty:
                print(f"No new ratings found after {max_consecutive_empty} consecutive batches. Extraction complete.")
                break
            
            # Scroll down to load more content
            print(f"Scrolling to load more content (batch {page+1})...")
            
            # More aggressive scrolling strategy
            try:
                # First scroll to bottom
                browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(5)  # Increased from 2 to 5
                
                # Then scroll up slightly to trigger loading
                browser.execute_script("window.scrollBy(0, -500);")
                time.sleep(3)  # Increased from 1 to 3
                
                # Finally scroll back down
                browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(5)  # Increased from 2 to 5
            except Exception as e:
                print(f"Error during scroll: {e}")
            
            # Increment page counter
            page += 1
            pbar.update(1)
            
            # Check if we've reached a maximum retry count
            if page > max_retries and max_pages is None:
                print(f"Reached maximum retry count ({max_retries}). Proceeding with {len(ratings)} ratings.")
                break
    
    else:
        # Original code for classic interface
        print("Using classic IMDb interface extraction method...")
        # Implementation omitted for brevity
    
    pbar.close()
    
    print(f"\nCompleted processing with {len(ratings)} total ratings found")
    return ratings

def export_imdb_ratings():
    """Main function to export IMDb ratings with manual assistance."""
    ensure_data_dir()
    
    browser = None
    try:
        print("\n===== IMDB RATING EXPORT =====")
        print("This script will help you export your IMDb movie ratings.")
        print("You'll need to log in manually to your IMDb account.")
        print("The script will then navigate to your ratings page and scrape them.")
        
        # Ask if user wants headless mode
        use_headless = input("\nUse headless mode for faster processing? (y/n, default: n): ").lower() == 'y'
        if use_headless:
            print("NOTE: Since you need to login manually, browser will only go headless AFTER login is complete.")
            print("WARNING: Headless mode may sometimes fail to maintain your login session. If this happens,")
            print("         you'll need to run the script again without headless mode.")
            print("WARNING: Headless mode may also cause the browser to disappear due to timeouts.")
            print("WARNING: For large number of ratings (1000+), we strongly recommend visible browser mode.")
            print("         We recommend using visible browser mode for most reliable results.")
            
            # Double confirm if they want headless mode
            headless_confirm = input("Are you sure you want to use headless mode? (y/n): ").lower() == 'y'
            if not headless_confirm:
                use_headless = False
                print("Using visible browser mode instead.")
        
        input("\nPress Enter to continue...")
        
        # Set up browser
        browser = setup_browser()
        
        # Manual login
        if not login_to_imdb_manually(browser):
            print("Login failed or was not confirmed. Exiting.")
            return False
        
        # Switch to headless mode after login if requested
        if use_headless:
            print("\nLogin successful! Switching to headless mode for faster processing...")
            
            # Before switching, verify we're logged in by checking for user menu
            try:
                # Store the current URL so we can return to it
                current_url = browser.current_url
                
                # Briefly navigate to the main page to ensure cookies are fully established
                browser.get("https://www.imdb.com")
                time.sleep(2)
                
                # Check if we can see a sign that we're logged in
                user_menu = browser.find_elements(By.CSS_SELECTOR, ".imdb-header__account-menu")
                if not user_menu:
                    print("Warning: Unable to verify login before switching to headless mode.")
                    use_headless_confirmed = input("Continue with headless mode anyway? (y/n): ").lower() == 'y'
                    if not use_headless_confirmed:
                        print("Continuing with visible browser instead.")
                        use_headless = False
            except Exception as e:
                print(f"Error verifying login: {e}")
                print("Continuing with visible browser for reliability.")
                use_headless = False
            
            if use_headless:
                # Save ALL cookies
                browser_cookies = browser.get_cookies()
                
                # Store the login URL to restore after headless switch
                ratings_url = "https://www.imdb.com/list/ratings"
                browser.quit()
                
                print("Creating new headless browser with your session...")
                try:
                    # Create a new headless browser with more parameters preserved
                    browser = setup_browser(headless=True)
                    
                    # First go to IMDB home to set the cookies
                    browser.get("https://www.imdb.com")
                    for cookie in browser_cookies:
                        try:
                            browser.add_cookie(cookie)
                        except Exception as e:
                            print(f"Warning: Couldn't add cookie: {e}")
                    
                    # Refresh to apply cookies
                    browser.refresh()
                    time.sleep(2)
                    
                    print("Headless browser set up with your login session")
                except Exception as e:
                    print(f"Error setting up headless browser: {e}")
                    print("Creating a new visible browser instead")
                    browser = setup_browser(headless=False)
                    
                    # Try to restore cookies
                    browser.get("https://www.imdb.com")
                    for cookie in browser_cookies:
                        try:
                            browser.add_cookie(cookie)
                        except:
                            pass
                    browser.refresh()
        
        print("\nFetching your IMDb ratings...")
        print("Navigating to your IMDb ratings page...")
        
        # Try navigating to ratings page with retries
        ratings_reached = False
        for attempt in range(3):
            try:
                # Navigate to ratings page, using better error handling
                ratings_url = "https://www.imdb.com/list/ratings"
                browser.get(ratings_url)
                time.sleep(5)  # Longer initial wait
                
                # Verify we reached the ratings page
                page_title = browser.title
                current_url = browser.current_url
                print(f"Current page: {current_url}")
                print(f"Page title: {page_title}")
                
                if "Your Ratings" in page_title or "ratings" in current_url.lower():
                    print("Successfully reached your ratings page!")
                    ratings_reached = True
                    break
                else:
                    print(f"Attempt {attempt+1}: Did not reach ratings page. Trying again...")
                    # Try the newer format URL
                    if attempt == 1:
                        try:
                            # Try with the user ID that matches what's in the URL
                            user_id = "ur60868178"  # This may need to be updated for different users
                            ratings_url = f"https://www.imdb.com/user/{user_id}/ratings"
                            browser.get(ratings_url)
                            time.sleep(5)
                            if "ratings" in browser.current_url.lower():
                                print("Successfully reached ratings page using alternate URL!")
                                ratings_reached = True
                                break
                        except:
                            pass
            except Exception as e:
                print(f"Error during attempt {attempt+1} to reach ratings page: {e}")
        
        if not ratings_reached:
            if use_headless:
                print("\nWARNING: Headless mode appears to have lost your login session.")
                print("This is a common issue with headless browsers.")
                print("The script will exit. Please run it again WITHOUT using headless mode.")
                return False
            else:
                print("\nNOTE: Could not automatically detect ratings page.")
                print("If you're not on your ratings page, you may need to navigate manually.")
                
                confirmation = input("Can you confirm you're seeing your ratings page? (y/n): ")
                if confirmation.lower() not in ['y', 'yes']:
                    print("Let's try to navigate to the ratings page manually...")
                    print("1. Click on your user icon in the top right")
                    print("2. Select 'Your Ratings' from the dropdown menu")
                    input("Press Enter once you've navigated to your ratings page...")
        
        # Save page source for debugging if needed
        try:
            with open("debug_imdb_page.html", "w", encoding="utf-8") as f:
                f.write(browser.page_source)
                print("Saved page HTML to debug_imdb_page.html for inspection")
        except Exception as e:
            print(f"Could not save debug HTML: {e}")
        
        # Process and fetch ratings
        ratings = fetch_imdb_ratings(browser)
        
        print(f"\nFound {len(ratings)} rated movies on IMDb")
        
        # Save ratings to file
        save_json(ratings, IMDB_EXPORT_PATH)
        
        print(f"Successfully exported IMDb ratings to {IMDB_EXPORT_PATH}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting IMDb ratings: {e}")
        print(f"Error: {str(e)}")
        
        # Recovery: try to save any ratings we've collected so far
        if 'ratings' in locals() and ratings:
            try:
                print(f"Attempting to save {len(ratings)} ratings collected before error...")
                save_json(ratings, IMDB_EXPORT_PATH)
                print(f"Successfully saved partial ratings to {IMDB_EXPORT_PATH}")
            except:
                print("Could not save partial ratings")
        
        return False
        
    finally:
        if browser:
            try:
                browser.quit()
            except:
                print("Note: Could not cleanly close browser")

if __name__ == "__main__":
    export_imdb_ratings() 