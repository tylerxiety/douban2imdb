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
RATING_CONFIRMATION_RETRIES = int(os.getenv("RATING_CONFIRMATION_RETRIES", "5"))  # Number of retries for rating confirmation
RATING_CONFIRMATION_WAIT = int(os.getenv("RATING_CONFIRMATION_WAIT", "30"))  # Seconds to wait for rating confirmation

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

def rate_movie_on_imdb(browser, imdb_id, rating, title=None, retry_count=0, test_mode=False):
    """Rate a movie on IMDb with retry logic and user assistance when needed."""
    try:
        # First access the movie page
        if not access_movie_page_by_id(browser, imdb_id):
            logger.error(f"Could not access movie page for {imdb_id}")
            return False
        
        # Get title from page if not provided
        if not title:
            try:
                title_element = WebDriverWait(browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .title-overview h1, .TitleHeader__TitleText"))
                )
                title = title_element.text
            except:
                title = browser.title.split(" - IMDb")[0] if " - IMDb" in browser.title else browser.title
        
        title_text = title or f"Movie {imdb_id}"
        print(f"\nRating {title_text} ({imdb_id}) as {rating}/10")
        
        # Take screenshot in test mode
        if test_mode:
            os.makedirs("../debug_logs/screenshots", exist_ok=True)
            screenshot_path = f"../debug_logs/screenshots/{imdb_id}.png"
            browser.save_screenshot(screenshot_path)
            print(f"Screenshot saved to {screenshot_path}")
            
            # In test mode, save the page source for debugging
            with open(f"../debug_logs/screenshots/{imdb_id}_page_source.html", "w", encoding="utf-8") as f:
                f.write(browser.page_source)
            print(f"Page source saved to ../debug_logs/screenshots/{imdb_id}_page_source.html")
            
            # Ask if user wants to highlight potential rating elements
            highlight_choice = input("Would you like to highlight potential rating elements for debugging? (y/n): ")
            if highlight_choice.lower() == 'y':
                highlighted_elements = highlight_potential_rating_elements(browser, rating)
                screenshot_path = f"../debug_logs/screenshots/{imdb_id}_highlighted.png"
                browser.save_screenshot(screenshot_path)
                print(f"Screenshot with highlighted elements saved to {screenshot_path}")
                
                # Ask if user wants to manually click a highlighted element
                manual_choice = input("Would you like to try clicking a highlighted element manually? (y/n): ")
                if manual_choice.lower() == 'y':
                    print("Please enter the number of the element to click (1, 2, 3, etc.):")
                    for i, (element, _) in enumerate(highlighted_elements):
                        print(f"{i+1}. {element.get_attribute('outerHTML')[:100]}...")
                    
                    element_choice = input("Enter element number (or 0 to skip): ")
                    if element_choice.isdigit() and 0 < int(element_choice) <= len(highlighted_elements):
                        element_idx = int(element_choice) - 1
                        selected_element = highlighted_elements[element_idx][0]
                        try:
                            # Try to click the element
                            browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", selected_element)
                            time.sleep(1)
                            browser.execute_script("arguments[0].click();", selected_element)
                            print(f"Clicked element {element_choice}")
                            time.sleep(2)
                            browser.save_screenshot(f"../debug_logs/screenshots/{imdb_id}_after_manual_click.png")
                            return True
                        except Exception as e:
                            print(f"Failed to click element: {e}")
        
        # Try to locate the rate button
        try:
            # Enhanced check for already rated content
            already_rated = False
            already_rated_selectors = [
                ".user-rating",                          # General user rating class
                "[data-testid='hero-rating-bar__user-rating']", # New IMDb layout user rating
                ".ipl-rating-star__rating",              # Rating star with value
                "button.ipl-rating-interactive__star-display", # Interactive rating display
                ".UserRatingButton__rating" # Newer IMDb user rating
            ]
            
            for selector in already_rated_selectors:
                elements = browser.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    # Check if any element contains rating text
                    for element in elements:
                        try:
                            text = element.text.strip()
                            if text and any(str(i) in text for i in range(1, 11)):
                                already_rated = True
                                logger.info(f"Found existing rating: '{text}'")
                                break
                        except:
                            pass
                
                if already_rated:
                    break
            
            if already_rated:
                print(f"Movie {title_text} is already rated on IMDb, skipping")
                return True
            
            # Locate and click the rate button
            print("Looking for rate button...")
            rate_button_selectors = [
                ".star-rating-button button",
                ".star-rating-widget button",
                "button[data-testid='hero-rating-bar__user-rating']",
                "[data-testid='hero-rating-bar__user-rating']",
                ".ipl-rating-star",
                "button.ipl-rating-interactive",
                ".UserRatingButton--default",
                ".RatingBarButtonBase",
                ".RatingsAddRating"
            ]
            
            rate_button = None
            for selector in rate_button_selectors:
                try:
                    rate_elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if rate_elements:
                        rate_button = rate_elements[0]
                        logger.info(f"Found rate button with selector: {selector}")
                        break
                except Exception as e:
                    if test_mode:
                        print(f"Error with selector {selector}: {str(e)[:100]}...")
            
            if test_mode and not rate_button:
                # Try to find buttons that could be the rate button
                print("Looking for any clickable buttons...")
                try:
                    all_buttons = browser.find_elements(By.TAG_NAME, "button")
                    print(f"Found {len(all_buttons)} buttons on the page")
                    for i, btn in enumerate(all_buttons[:5]):  # Show first 5 buttons
                        print(f"Button {i+1}: {btn.get_attribute('outerHTML')[:100]}...")
                except Exception as e:
                    print(f"Error listing buttons: {e}")
            
            if rate_button:
                print("Found rate button, clicking...")
                # Scroll to the rate button to ensure it's visible
                browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", rate_button)
                time.sleep(1)
                
                # Take screenshot of the rate button in test mode
                if test_mode:
                    screenshot_path = f"../debug_logs/screenshots/{imdb_id}_rate_button.png"
                    browser.save_screenshot(screenshot_path)
                    print(f"Rate button screenshot saved to {screenshot_path}")
                    
                # In test mode, automatically continue
                if test_mode:
                    print(f"TEST MODE: Would click rating element for {rating} stars")
                    print(f"Element found: {rating_element.get_attribute('outerHTML')}")
                    print("Automatically continuing with rating...")
                
                rate_button.click()
                time.sleep(2)  # Give more time for the rating dialog to appear
            else:
                print("Rate button not found. Automatically trying to find rating elements directly...")
                print("Looking for rating elements directly...")
                
            # Select the rating from the popup
            print("Looking for rating stars...")
            time.sleep(3)  # Increased wait time for the rating popup to load
            
            # Different sites have different rating UIs, try multiple selectors
            rating_selectors = [
                f"button[aria-label='{rating} stars']",
                f"button[aria-label='Rate {rating}']",
                f".star-rating-stars a[title='Click to rate: {rating}']",
                f"span.star-rating-star[title='Click to rate: {rating}']",
                f"button.ipl-rating-star--rate.ipl-rating-star--size-lg[aria-label='Rate {rating}']",
                f"button.ipl-rating-interactive__star[data-rating='{rating}']",
                f"button[data-testid='rate-{rating}']",
                f"button.RatingBarItem--clickable[data-testid='rating-{rating}']",
                f"button[data-rating='{rating}']",
                f"button.ipl-rating-star--size-lg[aria-label='Rate {rating}']",
                f"button[title='Click to rate: {rating}']",
                f"li[data-value='{rating}']",
                f"div[data-value='{rating}']",
                # New selectors for more current IMDb UI
                f"button.ipc-rating__star--rate.ipc-rating__star--base[aria-label='Rate {rating}']", 
                f"button.rating-star__star[data-label='{rating}']",
                f"button[rate-value='{rating}']",
                f".RatingBarItem[data-testid='rating-{rating}']",
                # Generic number-based selector
                f"button:nth-child({rating}) .rating-stars__star",
                # Target the touch overlay that's causing issues
                f"div.ipc-starbar__touch",
                f".ipc-rating-star-group button[aria-label='Rate {rating}']",
                f".ipc-starbar__rating__button[aria-label='Rate {rating}']"
            ]
            
            # Try to wait for rating elements to become clickable
            try:
                # Wait for any rating container to be present
                WebDriverWait(browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 
                    ".ipl-rating-selector, .stars-rating-widget, .RatingBarItem, [class*='rating'], [class*='star']"))
                )
                print("Rating container found, looking for specific rating element...")
            except TimeoutException:
                print("Rating container not found within timeout, will still try to find rating element...")
            
            rating_element = None
            for selector in rating_selectors:
                try:
                    elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        rating_element = elements[0]
                        logger.info(f"Found rating element with selector: {selector}")
                        break
                except Exception as e:
                    if test_mode:
                        print(f"Error with rating selector {selector}: {str(e)[:100]}...")
            
            if rating_element:
                print(f"Found rating element for {rating} stars, clicking...")
                if test_mode:
                    print(f"TEST MODE: Would click rating element for {rating} stars")
                    print(f"Element found: {rating_element.get_attribute('outerHTML')}")
                    print("Automatically continuing with rating...")
                
                # Scroll to the rating element to ensure it's visible
                browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", rating_element)
                time.sleep(2)  # Increased wait time
                
                # Take screenshot before clicking in test mode
                if test_mode:
                    screenshot_path = f"../debug_logs/screenshots/{imdb_id}_before_rating.png"
                    browser.save_screenshot(screenshot_path)
                
                # Special handling for IMDb touch overlay
                element_html = rating_element.get_attribute("outerHTML").lower()
                element_class = rating_element.get_attribute("class") or ""
                
                # Check if we're dealing with the touch overlay that's causing issues
                if "ipc-starbar__touch" in element_class or "ipc-starbar__touch" in element_html:
                    print("Detected IMDb touch overlay, using special handling")
                    try:
                        # First attempt: Try to find all stars and click the right one by position
                        parent = rating_element.find_element(By.XPATH, "..")
                        stars = parent.find_elements(By.CSS_SELECTOR, "button")
                        
                        if len(stars) >= int(rating):
                            # Use direct JavaScript click on the specific star
                            target_star = stars[int(rating)-1]
                            browser.execute_script("arguments[0].click();", target_star)
                            print(f"Clicked star {rating} using JavaScript execution on star by position")
                        else:
                            # Alternative: try to specifically locate the correct star
                            specific_star = browser.find_element(By.CSS_SELECTOR, f"button[aria-label='Rate {rating}']")
                            browser.execute_script("arguments[0].click();", specific_star)
                            print(f"Clicked star using specific selector")
                    except Exception as e:
                        print(f"Special handling initial attempt failed: {e}")
                        
                        try:
                            # Second attempt: Try to temporarily remove the overlay
                            browser.execute_script("arguments[0].style.pointerEvents = 'none';", rating_element)
                            time.sleep(0.5)
                            # Then find and click the actual button
                            actual_button = browser.find_element(By.CSS_SELECTOR, f"button[aria-label='Rate {rating}']")
                            browser.execute_script("arguments[0].click();", actual_button)
                            print("Clicked star after disabling overlay")
                        except Exception as e:
                            print(f"Special handling second attempt failed: {e}")
                            
                            try:
                                # Third attempt: Click at specific position within the starbar
                                starbar = browser.find_element(By.CSS_SELECTOR, ".ipc-starbar, .ipc-rating-star-group")
                                starbar_rect = starbar.rect
                                
                                # Calculate position based on rating (1-10)
                                width = starbar_rect['width']
                                x_offset = (width / 10) * int(rating) - (width / 20)  # Center of the target star
                                y_offset = starbar_rect['height'] / 2
                                
                                from selenium.webdriver.common.action_chains import ActionChains
                                actions = ActionChains(browser)
                                actions.move_to_element_with_offset(starbar, x_offset, y_offset)
                                actions.click()
                                actions.perform()
                                print(f"Clicked at calculated position within starbar")
                            except Exception as e:
                                print(f"Special handling third attempt failed: {e}")
                                
                                try:
                                    # Fourth attempt: Try to target the specific button class from the error message
                                    specific_buttons = browser.find_elements(By.CSS_SELECTOR, ".ipc-starbar__rating__button")
                                    if len(specific_buttons) >= int(rating):
                                        target_button = specific_buttons[int(rating)-1]
                                        # Try using tab to focus and then press Enter
                                        from selenium.webdriver.common.keys import Keys
                                        actions = ActionChains(browser)
                                        actions.move_to_element(target_button).perform()
                                        time.sleep(0.5)
                                        # Focus the element using JavaScript
                                        browser.execute_script("arguments[0].focus();", target_button)
                                        time.sleep(0.5)
                                        # Send Enter key
                                        target_button.send_keys(Keys.ENTER)
                                        print("Used keyboard Enter after focus on star button")
                                    else:
                                        print(f"Not enough specific buttons found: {len(specific_buttons)}")
                                except Exception as e:
                                    print(f"Special handling fourth attempt failed: {e}")
                                    
                                    try:
                                        # Fifth attempt (emergency): Try to completely remove the touch overlay from DOM
                                        browser.execute_script("""
                                        var overlays = document.querySelectorAll('.ipc-starbar__touch');
                                        for(var i=0; i < overlays.length; i++) {
                                            overlays[i].parentNode.removeChild(overlays[i]);
                                        }
                                        """)
                                        time.sleep(0.5)
                                        # Then try to find the stars again
                                        target_stars = browser.find_elements(By.CSS_SELECTOR, 
                                            f"button[aria-label='Rate {rating}'], .ipc-starbar__rating__button")
                                        if target_stars:
                                            browser.execute_script("arguments[0].click();", target_stars[0])
                                            print("Clicked star after removing overlay from DOM")
                                        else:
                                            print("No stars found after removing overlay")
                                    except Exception as e:
                                        print(f"Emergency DOM manipulation failed: {e}")
                                        # Now truly fall back to regular click methods
                else:
                    # Try multiple clicking methods, prioritizing JavaScript click
                    try:
                        # Method 1: JavaScript click (prioritized)
                        browser.execute_script("arguments[0].click();", rating_element)
                        print("Clicked using JavaScript execution")
                    except Exception as e:
                        print(f"JavaScript click failed: {e}")
                        try:
                            # Method 2: Standard click
                            rating_element.click()
                            print("Clicked using standard click")
                        except Exception as e:
                            print(f"Standard click failed: {e}")
                            try:
                                # Method 3: Actions click
                                from selenium.webdriver.common.action_chains import ActionChains
                                ActionChains(browser).move_to_element(rating_element).click().perform()
                                print("Clicked using ActionChains")
                            except Exception as e:
                                print(f"ActionChains click failed: {e}")
                                print("All click methods failed")
                
                time.sleep(5)  # Increased wait time for the rating to register
                
                # Look for and click the "Rate" confirmation button
                try:
                    print("Looking for 'Rate' confirmation button...")
                    # Wait for the Rate button to appear
                    WebDriverWait(browser, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 
                        ".ipc-rating-prompt, .ipc-promptable-dialog, [data-testid='promptable']"))
                    )
                    
                    # In test mode, show what's in the prompt dialog
                    if test_mode:
                        print("Rating dialog content:")
                        try:
                            dialog = browser.find_element(By.CSS_SELECTOR, ".ipc-rating-prompt, .ipc-promptable-dialog, [data-testid='promptable']")
                            dialog_html = dialog.get_attribute('outerHTML')
                            print(f"Dialog found: {dialog_html[:200]}...") # Show beginning of dialog HTML
                            
                            # Look for all buttons in the dialog
                            buttons = dialog.find_elements(By.TAG_NAME, "button")
                            print(f"Found {len(buttons)} buttons in dialog:")
                            for i, btn in enumerate(buttons[:5]):  # Show first 5 buttons
                                btn_text = btn.text.strip()
                                btn_html = btn.get_attribute('outerHTML')
                                print(f"Button {i+1}: Text='{btn_text}', HTML={btn_html[:100]}...")
                            
                            # Save dialog screenshot
                            screenshot_path = f"../debug_logs/screenshots/{imdb_id}_rating_dialog.png"
                            browser.save_screenshot(screenshot_path)
                            print(f"Rating dialog screenshot saved to {screenshot_path}")
                        except Exception as e:
                            print(f"Error examining dialog: {e}")
                    
                    # Find the Rate confirmation button within the rating dialog
                    rate_confirm_selectors = [
                        # First try to find buttons with exact "Rate" text 
                        ".ipc-rating-prompt button",
                        ".ipc-promptable-dialog button",
                        "[data-testid='promptable'] button:not([id='suggestion-search-button'])",
                        
                        # More specific selectors
                        "[data-testid='promptable'] button[type='button']",
                        ".ipc-rating-prompt__button",
                        ".ipc-promptable-dialog button:not([id='suggestion-search-button'])",
                        ".ipc-rating-prompt button.ipc-btn",
                        
                        # Avoid search button by only selecting within rating dialog
                        ".ipc-rating-prompt .ipc-btn",
                        "[data-testid='promptable'] .ipc-btn"
                    ]
                    
                    rate_confirm_button = None
                    for selector in rate_confirm_selectors:
                        try:
                            elements = browser.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                for elem in elements:
                                    elem_html = elem.get_attribute('outerHTML').lower()
                                    elem_text = elem.text.lower()
                                    
                                    # Skip search button
                                    if "search" in elem_html or "suggestion-search" in elem_html:
                                        continue
                                        
                                    # Prefer buttons with "rate" text
                                    if ("rate" in elem_text) or ("submit" in elem_text):
                                        rate_confirm_button = elem
                                        break
                                
                                # If no button with "rate" text was found, use the first one that's not the search button
                                if not rate_confirm_button and elements:
                                    for elem in elements:
                                        if "search" not in elem.get_attribute('id') and "search" not in elem.get_attribute('class'):
                                            rate_confirm_button = elem
                                            break
                        except Exception as e:
                            if test_mode:
                                print(f"Error with rate button selector {selector}: {str(e)[:100]}...")
                    
                    # Use XPath as a fallback
                    if not rate_confirm_button:
                        try:
                            # Look for any button with "Rate" text
                            xpath_selectors = [
                                "//div[contains(@class, 'ipc-rating-prompt')]//button[contains(text(), 'Rate')]",
                                "//div[@data-testid='promptable']//button[contains(text(), 'Rate')]",
                                "//div[contains(@class, 'ipc-promptable-dialog')]//button[not(@id='suggestion-search-button')]"
                            ]
                            
                            for xpath in xpath_selectors:
                                elements = browser.find_elements(By.XPATH, xpath)
                                if elements:
                                    for elem in elements:
                                        if "search" not in elem.get_attribute('id').lower():
                                            rate_confirm_button = elem
                                            print(f"Found rate button using XPath: {xpath}")
                                            break
                                if rate_confirm_button:
                                    break
                        except Exception as e:
                            print(f"XPath fallback failed: {e}")
                    
                    # If we still haven't found the button, try clicking the dialog bottom
                    if not rate_confirm_button:
                        try:
                            # Try clicking directly at coordinates of the "Rate" button
                            dialog = browser.find_element(By.CSS_SELECTOR, ".ipc-rating-prompt, .ipc-promptable-dialog, [data-testid='promptable']")
                            dialog_rect = dialog.rect
                            
                            # Calculate position for bottom center (likely location of the Rate button)
                            x_offset = dialog_rect['width'] / 2
                            y_offset = dialog_rect['height'] - 30  # 30px from bottom
                            
                            from selenium.webdriver.common.action_chains import ActionChains
                            actions = ActionChains(browser)
                            actions.move_to_element_with_offset(dialog, x_offset, y_offset)
                            actions.click()
                            actions.perform()
                            print("Clicked at likely Rate button position in dialog")
                            
                            if test_mode:
                                browser.save_screenshot(f"../debug_logs/screenshots/{imdb_id}_after_position_click.png")
                                print("Screenshot saved after position click")
                        except Exception as e:
                            print(f"Position-based click failed: {e}")
                    
                    if rate_confirm_button:
                        print("Found 'Rate' confirmation button, clicking to submit rating...")
                        # Scroll to the button to ensure it's visible
                        browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", rate_confirm_button)
                        time.sleep(1)
                        
                        if test_mode:
                            print(f"Rate button: {rate_confirm_button.get_attribute('outerHTML')}")
                            screenshot_path = f"../debug_logs/screenshots/{imdb_id}_rate_confirm_button.png"
                            browser.save_screenshot(screenshot_path)
                        
                        try:
                            # Try multiple clicking methods for the Rate button, prioritizing JavaScript click
                            try:
                                # JavaScript click (prioritized)
                                browser.execute_script("arguments[0].click();", rate_confirm_button)
                                print("Clicked Rate button using JavaScript execution")
                            except Exception as e:
                                print(f"JavaScript click on Rate button failed: {e}")
                                try:
                                    # Standard click
                                    rate_confirm_button.click()
                                    print("Clicked Rate button using standard click")
                                except Exception as e:
                                    print(f"Standard click on Rate button failed: {e}")
                                    try:
                                        # ActionChains click
                                        from selenium.webdriver.common.action_chains import ActionChains
                                        ActionChains(browser).move_to_element(rate_confirm_button).click().perform()
                                        print("Clicked Rate button using ActionChains")
                                    except Exception as e:
                                        print(f"All click methods for Rate button failed: {e}")
                            
                            print("Rating submission complete")
                            # Wait longer for any animations or page updates to complete
                            time.sleep(10)
                        except Exception as e:
                            print(f"Error clicking Rate confirmation button: {e}")
                    else:
                        print("Rate confirmation button not found - the rating may or may not be saved")
                        if test_mode:
                            # For debugging, save a screenshot to see what's available
                            browser.save_screenshot(f"../debug_logs/screenshots/{imdb_id}_rate_button_not_found.png")
                            print("Screenshot saved for debugging the missing Rate button")
                except Exception as e:
                    print(f"Error finding or handling the Rate confirmation button: {e}")
                    if test_mode:
                        print("This may be normal if the rating is saved automatically")
                
                # Take another screenshot after rating in test mode
                if test_mode:
                    screenshot_path = f"../debug_logs/screenshots/{imdb_id}_after_rating.png"
                    browser.save_screenshot(screenshot_path)
                    print(f"After-rating screenshot saved to {screenshot_path}")
                
                # Better check for confirmation
                confirmation_selectors = [
                    ".ipl-rating-interactive__star-rating",
                    ".user-rating",
                    ".imdb-rating .star-rating-text",
                    "[data-testid='hero-rating-bar__user-rating']",
                    ".ipl-rating-star__rating",
                    ".UserRatingButton__rating"
                ]
                
                # Wait longer for confirmation to appear
                time.sleep(RATING_CONFIRMATION_WAIT)
                
                confirmation_found = False
                for selector in confirmation_selectors:
                    elements = browser.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        for element in elements:
                            try:
                                text = element.text.strip()
                                if text and any(str(i) in text for i in range(1, 11)):
                                    print(f"Rating confirmation found: '{text}'")
                                    confirmation_found = True
                                    break
                            except:
                                pass
                    
                    if confirmation_found:
                        break
                
                if not confirmation_found:
                    print("No explicit rating confirmation found")
                    if retry_count < RATING_CONFIRMATION_RETRIES:
                        print(f"Automatically retrying rating (attempt {retry_count + 1}/{RATING_CONFIRMATION_RETRIES})")
                        time.sleep(2)  # Wait before retry
                        return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count + 1, test_mode)
                    else:
                        print(f"Failed to confirm rating after {RATING_CONFIRMATION_RETRIES} attempts")
                        if test_mode:
                            browser.save_screenshot(f"../debug_logs/screenshots/{imdb_id}_no_confirmation.png")
                            print(f"Screenshot saved for debugging the missing confirmation")
                        return False
                
                return True
                
            else:
                print("Rate button not found. Automatically trying to find rating elements directly...")
                print("Looking for rating elements directly...")
                return False
                
        except (NoSuchElementException, StaleElementReferenceException) as e:
            print(f"Error finding rating elements: {e}")
            print("Automatically retrying rating...")
            if retry_count < MAX_RETRIES:
                backoff_time = exponential_backoff(retry_count)
                logger.warning(f"Error with rating elements, retrying in {backoff_time:.2f}s")
                time.sleep(backoff_time)
                return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count + 1, test_mode)
            else:
                logger.error(f"Failed to find rating elements after {MAX_RETRIES} attempts")
                return False
            
    except Exception as e:
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error rating movie {imdb_id}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count + 1, test_mode)
        else:
            logger.error(f"Failed to rate movie {imdb_id} after {MAX_RETRIES} attempts: {e}")
            print("Maximum retries reached. Skipping this movie.")
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
        
        # Process each movie
        success_count = 0
        failure_count = 0
        processed_count = 0
        browser = None
        
        try:
            # Setup browser once for all movies
            browser = setup_browser(headless=False, proxy=PROXY)
            
            # Login first
            if not login_to_imdb_manually(browser):
                logger.error("Failed to login to IMDb")
                return False
            
            # Use tqdm for a progress bar
            for movie in tqdm(movies_to_migrate, desc=f"Rating movies"):
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
                        test_mode=test_mode
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
                        failure_count += 1
                    
                    # Random wait between movies to avoid detection
                    wait_time = random.uniform(WAIT_BETWEEN_MOVIES[0], WAIT_BETWEEN_MOVIES[1])
                    logger.info(f"Waiting {wait_time:.1f} seconds before next movie...")
                    time.sleep(wait_time)
                    
                except Exception as e:
                    logger.error(f"Error processing movie {title}: {e}")
                    failure_count += 1
        
        except Exception as e:
            logger.error(f"Error during processing: {e}")
        
        # Print summary
        print("\n=== Migration Summary ===")
        print(f"Total processed: {processed_count}")
        print(f"Successfully rated: {success_count}")
        print(f"Failed to rate: {failure_count}")
        print(f"Total rated so far: {len(progress_data['processed_imdb_ids'])}")
        print(f"Remaining to rate: {total_movies - len(progress_data['processed_imdb_ids'])}")
        
        return success_count > 0
    
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

def migrate_ratings_with_option(option=None):
    """Main function for migrating ratings with a pre-selected option."""
    print("\n===== DOUBAN TO IMDB MIGRATION =====")
    print("This script will help you migrate your Douban movie ratings to IMDb.")
    
    if option is None:
        print("\nChoose an option:")
        print("1. Create migration plan")
        print("2. Execute migration plan")
        print("3. Create plan and execute immediately")
        
        choice = input("\nEnter your choice (1-3): ")
    else:
        choice = str(option)
    
    # Rest of your function using the choice variable
    # ...

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
            logging.FileHandler("../logs/migration.log"),
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