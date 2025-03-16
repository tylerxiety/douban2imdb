"""
Module for exporting user ratings from IMDb.
"""
import os
import time
import re
import json
import logging
import random
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import chromedriver_autoinstaller
from tqdm import tqdm
from dotenv import load_dotenv

from utils import ensure_data_dir, save_json, logger, random_sleep, get_random_user_agent, exponential_backoff

# Load environment variables
load_dotenv()

# IMDb account info
IMDB_USERNAME = os.getenv("IMDB_USERNAME")
IMDB_PASSWORD = os.getenv("IMDB_PASSWORD")
IMDB_EXPORT_PATH = os.getenv("IMDB_EXPORT_PATH", "data/imdb_ratings.json")

# Anti-scraping constants
IMDB_MIN_PAGE_DELAY = float(os.getenv("IMDB_MIN_PAGE_DELAY", "3.0"))
IMDB_MAX_PAGE_DELAY = float(os.getenv("IMDB_MAX_PAGE_DELAY", "7.0"))
MAX_PAGES_PER_SESSION = int(os.getenv("IMDB_MAX_PAGES_PER_SESSION", "10"))  # IMDb is more sensitive
MAX_RETRIES = 3  # Maximum number of retries for failures

def setup_browser():
    """Set up and return a Selenium browser instance with anti-scraping measures."""
    # Auto-install chromedriver that matches the Chrome version
    chromedriver_autoinstaller.install()
    
    chrome_options = Options()
    
    # Only use headless mode if specifically requested
    headless = os.getenv("HEADLESS_BROWSER", "false").lower() == "true"
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

def login_to_imdb(browser):
    """Login to IMDb using provided credentials with anti-scraping measures."""
    try:
        # Add initial delay before navigating to IMDb
        random_sleep(1, 3)
        
        browser.get("https://www.imdb.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.imdb.com%2Fregistration%2Fap-signin-handler%2Fimdb_us&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=imdb_us&openid.mode=checkid_setup&siteState=eyJvcGVuaWQuYXNzb2NfaGFuZGxlIjoiaW1kYl91cyIsInJlZGlyZWN0VG8iOiJodHRwczovL3d3dy5pbWRiLmNvbS8_cmVmXz1sb2dpbiJ9&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
        
        # Check if we are on the login page
        try:
            # Enter email/username with humanized typing
            email_input = WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.ID, "ap_email"))
            )
            
            # Type username with random delays between characters
            for char in IMDB_USERNAME:
                email_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))  # Mimic human typing
            
            random_sleep(0.5, 1.5)
            
            # Enter password with humanized typing
            password_input = browser.find_element(By.ID, "ap_password")
            for char in IMDB_PASSWORD:
                password_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))  # Mimic human typing
            
            random_sleep(0.5, 1.5)
            
            # Add a small random scroll before clicking sign-in
            scroll_amount = random.randint(0, 50)
            browser.execute_script(f"window.scrollTo(0, {scroll_amount});")
            
            # Click sign-in button
            signin_button = browser.find_element(By.ID, "signInSubmit")
            signin_button.click()
            
            # Check for CAPTCHA and handle it if present
            try:
                captcha_element = WebDriverWait(browser, 3).until(
                    EC.presence_of_element_located((By.ID, "auth-captcha-image"))
                )
                if captcha_element:
                    logger.warning("CAPTCHA detected! Please solve it manually.")
                    # Pause to allow manual CAPTCHA solving
                    print("CAPTCHA detected! Please solve it in the browser window and press Enter to continue...")
                    input()
            except:
                # No CAPTCHA found, continue
                pass
            
            # Wait for login to complete
            WebDriverWait(browser, 15).until(
                EC.presence_of_element_located((By.ID, "navUserMenu"))
            )
            logger.info("Successfully logged in to IMDb")
            
            # Add a longer delay after successful login
            random_sleep(2, 4)
            
        except (TimeoutException, NoSuchElementException) as e:
            # Check if we're already logged in
            if "Sign In" not in browser.title:
                logger.info("Already logged in to IMDb")
            else:
                logger.error(f"Login page has changed or error occurred: {e}")
                raise
            
    except Exception as e:
        logger.error(f"Failed to login to IMDb: {e}")
        raise

def fetch_imdb_ratings(browser):
    """Fetch all movie ratings for the current user with anti-scraping measures."""
    ratings = []
    page = 1
    has_next_page = True
    
    # Create progress bar
    pbar = tqdm(desc="Fetching IMDb ratings", unit="page")
    
    # Create a counter for session pages
    session_page_count = 0
    
    # Navigate to ratings page with delay
    random_sleep(1, 3)
    browser.get("https://www.imdb.com/list/ratings")
    
    while has_next_page:
        # Check if we need to restart the browser session
        if session_page_count >= MAX_PAGES_PER_SESSION:
            logger.info(f"Reached maximum pages per session ({MAX_PAGES_PER_SESSION}), restarting browser")
            # Close current browser
            browser.quit()
            
            # Add a significant delay before starting a new session
            random_sleep(45, 90)  # Longer delay for IMDb as it's more sensitive
            
            # Create a new browser and login again
            browser = setup_browser()
            login_to_imdb(browser)
            
            # Navigate back to ratings page at the correct page
            start_url = f"https://www.imdb.com/list/ratings?page={page}"
            browser.get(start_url)
            
            # Reset session counter
            session_page_count = 0
        
        try:
            # Random delay before parsing the page
            random_sleep(IMDB_MIN_PAGE_DELAY, IMDB_MAX_PAGE_DELAY)
            
            # Wait for ratings to load
            WebDriverWait(browser, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".lister-list"))
            )
            
            # Add human-like scrolling
            scroll_height = browser.execute_script("return document.body.scrollHeight")
            for _ in range(random.randint(3, 6)):  # Random number of scroll actions
                # Scroll to random positions
                scroll_position = random.randint(100, max(200, scroll_height - 200))
                browser.execute_script(f"window.scrollTo(0, {scroll_position});")
                time.sleep(random.uniform(0.5, 2.0))  # Random delay between scrolls
            
            # Parse the page
            soup = BeautifulSoup(browser.page_source, 'html.parser')
            movie_items = soup.select(".lister-item")
            
            if not movie_items:
                logger.info(f"No movies found on page {page}, ending search")
                break
            
            for item in movie_items:
                try:
                    # Extract movie info
                    title_elem = item.select_one(".lister-item-header a")
                    title = title_elem.text.strip()
                    imdb_url = "https://www.imdb.com" + title_elem["href"]
                    imdb_id = re.search(r"title/(tt\d+)/", imdb_url).group(1)
                    
                    # Extract year
                    year_elem = item.select_one(".lister-item-year")
                    year_text = year_elem.text.strip() if year_elem else ""
                    year_match = re.search(r"\((\d{4})\)", year_text)
                    year = year_match.group(1) if year_match else None
                    
                    # Extract rating - IMDb displays this as "Your Rating: X" in the ratings page
                    rating_elem = item.select_one(".your-rating-rating")
                    if not rating_elem:
                        continue
                    
                    rating_text = rating_elem.text.strip()
                    rating_value = int(rating_text) if rating_text.isdigit() else None
                    
                    # Extract director and other info
                    info_elem = item.select_one(".lister-item-content p:nth-child(5)")
                    info_text = info_elem.text.strip() if info_elem else ""
                    
                    # Add to ratings list
                    ratings.append({
                        "title": title,
                        "imdb_id": imdb_id,
                        "imdb_url": imdb_url,
                        "rating": rating_value,
                        "year": year,
                        "info": info_text
                    })
                    
                except Exception as e:
                    logger.warning(f"Error processing movie item: {e}")
                    continue
            
            # Check for next page
            next_link = soup.select_one(".next-page")
            if next_link and not "disabled" in next_link.get("class", []):
                next_page_url = "https://www.imdb.com" + next_link.find("a")["href"]
                
                # Random delay before navigating to next page
                random_sleep(IMDB_MIN_PAGE_DELAY, IMDB_MAX_PAGE_DELAY)
                
                browser.get(next_page_url)
                page += 1
                session_page_count += 1
                pbar.update(1)
            else:
                has_next_page = False
                
        except TimeoutException as e:
            # Use exponential backoff for retries
            backoff_time = exponential_backoff(0)
            logger.warning(f"Timeout loading page {page}, retrying in {backoff_time:.2f}s")
            time.sleep(backoff_time)
            browser.refresh()
            continue
            
        except Exception as e:
            # Try using exponential backoff for other errors
            if session_page_count > 0:  # Only retry if we've already successfully loaded at least one page
                backoff_time = exponential_backoff(0)
                logger.error(f"Error fetching page {page}, retrying in {backoff_time:.2f}s: {e}")
                time.sleep(backoff_time)
                browser.refresh()
                continue
            else:
                logger.error(f"Error fetching page {page}: {e}")
                break
    
    pbar.close()
    return ratings

def export_imdb_ratings():
    """Main function to export IMDb ratings with anti-scraping measures."""
    ensure_data_dir()
    
    if not IMDB_USERNAME or not IMDB_PASSWORD:
        logger.error("IMDb credentials not found in .env file")
        return False
    
    browser = None
    try:
        browser = setup_browser()
        login_to_imdb(browser)
        
        logger.info("Fetching ratings for IMDb user")
        ratings = fetch_imdb_ratings(browser)
        
        logger.info(f"Found {len(ratings)} rated movies on IMDb")
        
        # Save ratings to file
        save_json(ratings, IMDB_EXPORT_PATH)
        
        return True
        
    except Exception as e:
        logger.error(f"Error exporting IMDb ratings: {e}")
        return False
        
    finally:
        if browser:
            browser.quit()

if __name__ == "__main__":
    if export_imdb_ratings():
        print(f"Successfully exported IMDb ratings to {IMDB_EXPORT_PATH}")
    else:
        print("Failed to export IMDb ratings. Check the log for details.") 