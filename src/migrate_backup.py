"""
Script to migrate ratings from Douban to IMDb.
"""
import os
import time
import json
import logging
import random
import multiprocessing
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

# Constants
MAX_RETRIES = 5  # Increased from 3 to 5 for better retry handling
SPEED_MODE = False  # Set to True to disable images for faster loading
CONNECTION_TIMEOUT = 90  # Seconds to wait for connections before timeout
WAIT_BETWEEN_MOVIES = (1, 2)  # Reduced wait between movies for faster processing
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
                "profile.default_content_setting_values.notifications": 2
            }
            options.add_experimental_option("prefs", prefs)
        
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
        time.sleep(random.uniform(0.5, 1))
        
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
            os.makedirs("data/screenshots", exist_ok=True)
            screenshot_path = f"data/screenshots/{imdb_id}.png"
            browser.save_screenshot(screenshot_path)
            print(f"Screenshot saved to {screenshot_path}")
            
            # In test mode, save the page source for debugging
            with open(f"data/screenshots/{imdb_id}_page_source.html", "w", encoding="utf-8") as f:
                f.write(browser.page_source)
            print(f"Page source saved to data/screenshots/{imdb_id}_page_source.html")
            
            # Ask if user wants to highlight potential rating elements
            highlight_choice = input("Would you like to highlight potential rating elements for debugging? (y/n): ")
            if highlight_choice.lower() == 'y':
                highlighted_elements = highlight_potential_rating_elements(browser, rating)
                screenshot_path = f"data/screenshots/{imdb_id}_highlighted.png"
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
                            browser.save_screenshot(f"data/screenshots/{imdb_id}_after_manual_click.png")
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
                    screenshot_path = f"data/screenshots/{imdb_id}_rate_button.png"
                    browser.save_screenshot(screenshot_path)
                    print(f"Rate button screenshot saved to {screenshot_path}")
                    
                # Check if the user wants to continue in test mode
                if test_mode:
                    choice = input("Continue with rating? (y/n): ")
                    if choice.lower() != 'y':
                        return False
                
                rate_button.click()
                time.sleep(2)  # Give more time for the rating dialog to appear
            else:
                print("Rate button not found. Here are two ways to proceed:")
                print("1. Try to find rating elements directly")
                print("2. Skip this movie")
                choice = input("Enter 1 to try finding rating elements, any other key to skip: ")
                if choice == "1":
                    print("Looking for rating elements directly...")
                else:
                    print("Skipping this movie...")
                    return False
            
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
                    choice = input("Press Enter to continue with rating or type 'skip' to skip: ")
                    if choice.lower() == 'skip':
                        return False
                
                # Scroll to the rating element to ensure it's visible
                browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", rating_element)
                time.sleep(2)  # Increased wait time
                
                # Take screenshot before clicking in test mode
                if test_mode:
                    screenshot_path = f"data/screenshots/{imdb_id}_before_rating.png"
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
                    # Try multiple clicking methods
                    try:
                        # Method 1: Standard click
                        rating_element.click()
                    except Exception as e:
                        print(f"Standard click failed: {e}")
                        try:
                            # Method 2: JavaScript click
                            browser.execute_script("arguments[0].click();", rating_element)
                            print("Clicked using JavaScript execution")
                        except Exception as e:
                            print(f"JavaScript click failed: {e}")
                            try:
                                # Method 3: Actions click
                                from selenium.webdriver.common.action_chains import ActionChains
                                ActionChains(browser).move_to_element(rating_element).click().perform()
                                print("Clicked using ActionChains")
                            except Exception as e:
                                print(f"ActionChains click failed: {e}")
                                print("All click methods failed")
                
                time.sleep(3)  # Increased wait time for the rating to register
                
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
                            screenshot_path = f"data/screenshots/{imdb_id}_rating_dialog.png"
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
                                browser.save_screenshot(f"data/screenshots/{imdb_id}_after_position_click.png")
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
                            screenshot_path = f"data/screenshots/{imdb_id}_rate_confirm_button.png"
                            browser.save_screenshot(screenshot_path)
                        
                        try:
                            # Try multiple clicking methods for the Rate button
                            try:
                                # Standard click
                                rate_confirm_button.click()
                            except Exception as e:
                                print(f"Standard click on Rate button failed: {e}")
                                try:
                                    # JavaScript click
                                    browser.execute_script("arguments[0].click();", rate_confirm_button)
                                    print("Clicked Rate button using JavaScript execution")
                                except Exception as e:
                                    print(f"JavaScript click on Rate button failed: {e}")
                                    try:
                                        # ActionChains click
                                        from selenium.webdriver.common.action_chains import ActionChains
                                        ActionChains(browser).move_to_element(rate_confirm_button).click().perform()
                                        print("Clicked Rate button using ActionChains")
                                    except Exception as e:
                                        print(f"All click methods for Rate button failed: {e}")
                            
                            print("Rating submission complete")
                        except Exception as e:
                            print(f"Error clicking Rate confirmation button: {e}")
                    else:
                        print("Rate confirmation button not found - the rating may or may not be saved")
                        if test_mode:
                            # For debugging, save a screenshot to see what's available
                            browser.save_screenshot(f"data/screenshots/{imdb_id}_rate_button_not_found.png")
                            print("Screenshot saved for debugging the missing Rate button")
                except Exception as e:
                    print(f"Error finding or handling the Rate confirmation button: {e}")
                    if test_mode:
                        print("This may be normal if the rating is saved automatically")
                
                # Take another screenshot after rating in test mode
                if test_mode:
                    screenshot_path = f"data/screenshots/{imdb_id}_after_rating.png"
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
                    choice = input("Press Enter if the rating was successful, or type 'retry' to try again: ")
                    if choice.lower() == 'retry':
                        return rate_movie_on_imdb(browser, imdb_id, rating, title, 0, test_mode)
                
                return True
                
            else:
                print("Rating selection not found. Please try rating manually.")
                if test_mode:
                    # Try clicking on the rating widget container to see if that brings up stars
                    containers = browser.find_elements(By.CSS_SELECTOR, ".star-rating-widget, .ipl-rating-interactive, .RatingBarWrapper")
                    if containers:
                        print("Found rating container, trying to click it...")
                        try:
                            containers[0].click()
                            time.sleep(1)
                            browser.save_screenshot(f"data/screenshots/{imdb_id}_after_container_click.png")
                            print("Clicked container, check screenshot to see if stars appeared")
                        except:
                            print("Failed to click container")
                
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
            return rate_movie_on_imdb(browser, imdb_id, rating, title, retry_count + 1, test_mode)
        else:
            logger.error(f"Failed to rate movie {imdb_id} after {MAX_RETRIES} attempts: {e}")
            print("Manual intervention required for this movie.")
            choice = input("Press Enter to skip or type 'retry' to try once more: ")
            if choice.lower() == "retry":
                return rate_movie_on_imdb(browser, imdb_id, rating, title, 0, test_mode)
            return False

def execute_migration_plan(migration_plan, max_movies=None, test_mode=False, parallel=False):
    """Execute the migration plan by rating movies on IMDb."""
    # Get the movies to migrate
    movies_to_migrate = migration_plan.get("to_migrate", [])
    total_movies = len(movies_to_migrate)
    
    if not movies_to_migrate:
        logger.warning("No movies to migrate found in plan")
        return False
    
    if max_movies:
        movies_to_migrate = movies_to_migrate[:max_movies]
        logger.info(f"Processing {len(movies_to_migrate)} out of {total_movies} movies (limited by max_movies)")
    else:
        logger.info(f"Processing all {total_movies} movies from migration plan")
    
    if test_mode:
        print(f"RUNNING IN TEST MODE: Will provide more debug information and save screenshots")
        os.makedirs("data/screenshots", exist_ok=True)
    
    # Handle parallel processing
    if parallel and not test_mode:
        num_processes = min(multiprocessing.cpu_count(), 4)  # Use up to 4 processes
        logger.info(f"Running in parallel mode with {num_processes} processes")
        
        # Split the movies into chunks for each process
        chunk_size = len(movies_to_migrate) // num_processes
        if chunk_size == 0:
            chunk_size = 1
        
        chunks = []
        for i in range(0, len(movies_to_migrate), chunk_size):
            chunks.append(movies_to_migrate[i:i + chunk_size])
        
        # Let the user confirm once for all processes
        confirmation = input(f"Ready to rate {len(movies_to_migrate)} movies in parallel using {num_processes} processes? (y/n): ")
        if confirmation.lower() != "y":
            print("Aborting migration")
            return False
        
        print("\nIMPORTANT: Multiple browser windows will open. You need to log in to IMDb in EACH window.")
        print("Please wait for all browser windows to appear before proceeding with login.\n")
        
        # Create and start processes
        processes = []
        for i, chunk in enumerate(chunks):
            p = multiprocessing.Process(
                target=process_movie_chunk,
                args=(chunk, i, test_mode)
            )
            processes.append(p)
            p.start()
        
        # Wait for all processes to complete
        for p in processes:
            p.join()
        
        logger.info("All parallel processes completed")
        return True
    
    # Let the user confirm
    confirmation = input(f"Ready to rate {len(movies_to_migrate)} movies on IMDb? (y/n): ")
    if confirmation.lower() != "y":
        print("Aborting migration")
        return False
    
    # Set up browser
    browser = setup_browser(headless=False, proxy=PROXY)  # Force visible browser for manual login
    
    try:
        # Login first
        if not login_to_imdb_manually(browser):
            logger.error("Failed to log in to IMDb")
            return False
        
        # Process each movie
        successful = 0
        failed = 0
        skipped = 0
        
        # Use tqdm for progress tracking
        for movie in tqdm(movies_to_migrate, desc="Rating movies on IMDb"):
            imdb_id = movie.get("imdb_id")
            douban_title = movie.get("douban_title", "Unknown Title")
            douban_rating = movie.get("douban_rating")
            
            if not imdb_id or not douban_rating:
                logger.warning(f"Missing IMDb ID or rating for {douban_title}, skipping")
                skipped += 1
                continue
            
            logger.info(f"Processing {douban_title} ({imdb_id}) with rating {douban_rating}")
            
            # Rate the movie
            result = rate_movie_on_imdb(
                browser, 
                imdb_id, 
                douban_rating, 
                title=douban_title,
                test_mode=test_mode
            )
            
            if result:
                successful += 1
                # Add a random delay between movies to avoid being detected as a bot
                delay = random.uniform(WAIT_BETWEEN_MOVIES[0], WAIT_BETWEEN_MOVIES[1])
                logger.info(f"Waiting {delay:.1f} seconds before next movie...")
                time.sleep(delay)
            else:
                failed += 1
        
        # Print summary
        print("\n=== Migration Summary ===")
        print(f"Successfully rated: {successful}")
        print(f"Failed to rate: {failed}")
        print(f"Skipped: {skipped}")
        print(f"Total processed: {successful + failed + skipped}")
        
        return successful > 0
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False
    finally:
        # Always close the browser
        try:
            browser.quit()
        except:
            pass

def process_movie_chunk(movies_chunk, process_id, test_mode=False):
    """Process a chunk of movies in a separate process."""
    logger.info(f"Process {process_id}: Starting to process {len(movies_chunk)} movies")
    
    # Set up browser
    browser = setup_browser(headless=False, proxy=PROXY)
    
    try:
        # Login first
        if not login_to_imdb_manually(browser):
            logger.error(f"Process {process_id}: Failed to log in to IMDb")
            return False
        
        # Process each movie
        successful = 0
        failed = 0
        skipped = 0
        
        # Use tqdm for progress tracking
        for movie in tqdm(movies_chunk, desc=f"Process {process_id}: Rating movies"):
            imdb_id = movie.get("imdb_id")
            douban_title = movie.get("douban_title", "Unknown Title")
            douban_rating = movie.get("douban_rating")
            
            if not imdb_id or not douban_rating:
                logger.warning(f"Process {process_id}: Missing IMDb ID or rating for {douban_title}, skipping")
                skipped += 1
                continue
            
            logger.info(f"Process {process_id}: Processing {douban_title} ({imdb_id}) with rating {douban_rating}")
            
            # Rate the movie
            result = rate_movie_on_imdb(
                browser, 
                imdb_id, 
                douban_rating, 
                title=douban_title,
                test_mode=test_mode
            )
            
            if result:
                successful += 1
                # Add a random delay between movies to avoid being detected as a bot
                delay = random.uniform(WAIT_BETWEEN_MOVIES[0], WAIT_BETWEEN_MOVIES[1])
                logger.info(f"Process {process_id}: Waiting {delay:.1f} seconds before next movie...")
                time.sleep(delay)
            else:
                failed += 1
        
        # Print summary
        print(f"\n=== Process {process_id} Migration Summary ===")
        print(f"Successfully rated: {successful}")
        print(f"Failed to rate: {failed}")
        print(f"Skipped: {skipped}")
        print(f"Total processed: {successful + failed + skipped}")
        
        return successful > 0
        
    except Exception as e:
        logger.error(f"Process {process_id}: Error during migration: {e}")
        return False
    finally:
        # Always close the browser
        try:
            browser.quit()
        except:
            pass

if __name__ == "__main__":
    # Create argument parser
    parser = argparse.ArgumentParser(description="Migrate Douban ratings to IMDb")
    parser.add_argument("--create-plan", action="store_true", help="Create a migration plan")
    parser.add_argument("--execute-plan", action="store_true", help="Execute the migration plan")
    parser.add_argument("--max-movies", type=int, help="Maximum number of movies to process")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode with additional debug info")
    parser.add_argument("--speed-mode", action="store_true", help="Run in speed mode (disable images for faster loading)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--parallel", action="store_true", help="Run migration in parallel mode with multiple processes")
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
                execute_migration_plan(migration_plan, max_movies=args.max_movies, test_mode=args.test_mode, parallel=args.parallel)
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
            execute_migration_plan(migration_plan, max_movies=args.max_movies, test_mode=args.test_mode, parallel=args.parallel)
        else:
            logger.error("Failed to load migration plan")
    else:
        migrate_ratings()