"""
Module for exporting user ratings from Douban.
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

# Douban account info
DOUBAN_USERNAME = os.getenv("DOUBAN_USERNAME")
DOUBAN_PASSWORD = os.getenv("DOUBAN_PASSWORD")
DOUBAN_EXPORT_PATH = os.getenv("DOUBAN_EXPORT_PATH", "data/douban_ratings.json")

# Anti-scraping constants
DOUBAN_MIN_PAGE_DELAY = float(os.getenv("DOUBAN_MIN_PAGE_DELAY", "2.0"))
DOUBAN_MAX_PAGE_DELAY = float(os.getenv("DOUBAN_MAX_PAGE_DELAY", "5.0"))
DOUBAN_MIN_MOVIE_DELAY = float(os.getenv("DOUBAN_MIN_MOVIE_DELAY", "1.0"))
DOUBAN_MAX_MOVIE_DELAY = float(os.getenv("DOUBAN_MAX_MOVIE_DELAY", "3.0"))
MAX_PAGES_PER_SESSION = int(os.getenv("DOUBAN_MAX_PAGES_PER_SESSION", "20"))  # Limit pages per session
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

def login_to_douban(browser):
    """Login to Douban using provided credentials with anti-scraping measures."""
    try:
        browser.get("https://www.douban.com/")
        
        # Add random delay before login to mimic human behavior
        random_sleep(1, 3)
        
        # Check if we need to login
        try:
            # Click the login button
            login_link = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, "登录"))
            )
            login_link.click()
            
            # Random delay before next action
            random_sleep(1, 2)
            
            # Switch to account login
            account_login = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "account-tab-account"))
            )
            account_login.click()
            
            # Random delay before entering credentials
            random_sleep(0.5, 1.5)
            
            # Enter username and password with random delays between keystrokes
            username_input = WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            # Type username with random delays between characters
            for char in DOUBAN_USERNAME:
                username_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))  # Mimic human typing
            
            random_sleep(0.3, 1.0)
            
            password_input = browser.find_element(By.ID, "password")
            # Type password with random delays between characters
            for char in DOUBAN_PASSWORD:
                password_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))  # Mimic human typing
            
            random_sleep(0.5, 1.5)
            
            # Click login button
            login_button = browser.find_element(By.CLASS_NAME, "account-form-field-submit")
            login_button.click()
            
            # First check for CAPTCHA
            try:
                captcha_element = WebDriverWait(browser, 3).until(
                    EC.presence_of_element_located((By.ID, "captcha_image"))
                )
                if captcha_element:
                    logger.warning("CAPTCHA detected! Please solve it manually.")
                    # Pause to allow manual CAPTCHA solving
                    print("CAPTCHA detected! Please solve it in the browser window and press Enter to continue...")
                    input()
            except:
                # No CAPTCHA found, continue
                pass
            
            # Wait for QR code to appear (Douban may use QR code for 2FA)
            logger.info("Checking for QR code...")
            time.sleep(3)
            
            # Look for QR code elements
            qr_elements = browser.find_elements(By.CSS_SELECTOR, "img[src*='qrcode']")
            if qr_elements:
                logger.info("QR code detected! Please scan it with your Douban mobile app.")
                print("\n⚠️ PLEASE SCAN THE QR CODE with your Douban mobile app ⚠️")
                input("Press Enter AFTER you have successfully scanned the QR code and completed the login...")
                logger.info("Continuing after QR code scan...")
                time.sleep(3)
            
            # Wait for login to complete
            try:
                WebDriverWait(browser, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "nav-user-account"))
                )
                logger.info("Successfully logged in to Douban")
            except TimeoutException:
                # Check if we're on the main page anyway
                if "www.douban.com" in browser.current_url:
                    logger.info("Successfully logged in to Douban (detected by URL)")
                else:
                    logger.warning("Login may not have completed successfully. Please check the browser.")
                    input("Press Enter to continue if login is successful, or Ctrl+C to abort...")
            
            # Add a longer delay after successful login
            random_sleep(2, 4)
            
        except (TimeoutException, NoSuchElementException) as e:
            logger.info(f"Already logged in or login page has changed: {e}")
            
    except Exception as e:
        logger.error(f"Failed to login to Douban: {e}")
        raise

def get_user_id(browser):
    """Extract the user ID from the Douban page."""
    try:
        # Add randomized delay before getting user ID
        random_sleep(1, 2)
        
        browser.get("https://www.douban.com/mine/")
        # Get user profile URL which contains the user ID
        profile_link = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".nav-user-account a"))
        )
        profile_url = profile_link.get_attribute("href")
        user_id = profile_url.split('/')[-2]
        
        # Add small random delay after getting user ID
        random_sleep(0.5, 1.5)
        
        return user_id
    except Exception as e:
        logger.error(f"Failed to get user ID: {e}")
        raise

def extract_imdb_id(browser, douban_url, retry_count=0):
    """
    Extract IMDb ID from Douban movie page with anti-scraping measures.
    
    Args:
        browser: Selenium browser instance
        douban_url: URL of the Douban movie page
        retry_count: Current retry attempt
        
    Returns:
        IMDb ID if found, None otherwise
    """
    try:
        # Navigate to the movie page with anti-scraping delay
        browser.get(douban_url)
        
        # Wait for the page to load with random timing
        delay = random.uniform(2, 4)
        WebDriverWait(browser, delay).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#content"))
        )
        
        # Add a small random scroll to mimic human behavior
        scroll_amount = random.randint(100, 300)
        browser.execute_script(f"window.scrollTo(0, {scroll_amount});")
        
        # Use BeautifulSoup to parse the page
        soup = BeautifulSoup(browser.page_source, 'html.parser')
        
        # Look for IMDb ID in the info section
        info_section = soup.select_one("#info")
        if not info_section:
            return None
        
        # Look for IMDb link or ID in the text
        imdb_text = info_section.text
        imdb_match = re.search(r'IMDb:\s*(tt\d+)', imdb_text)
        if imdb_match:
            return imdb_match.group(1)
        
        # If not found in text, look for links to IMDb
        imdb_link = info_section.select_one('a[href*="imdb.com/title/"]')
        if imdb_link:
            link_match = re.search(r'title/(tt\d+)', imdb_link['href'])
            if link_match:
                return link_match.group(1)
        
        return None
        
    except Exception as e:
        # Use exponential backoff for retries
        if retry_count < MAX_RETRIES:
            backoff_time = exponential_backoff(retry_count)
            logger.warning(f"Error extracting IMDb ID from {douban_url}, retrying in {backoff_time:.2f}s: {e}")
            time.sleep(backoff_time)
            return extract_imdb_id(browser, douban_url, retry_count + 1)
        else:
            logger.warning(f"Failed to extract IMDb ID from {douban_url} after {MAX_RETRIES} attempts: {e}")
            return None

def fetch_movie_ratings(browser, user_id):
    """Fetch all movie ratings for the given user with anti-scraping measures."""
    ratings = []
    page = 1
    has_next_page = True
    
    # Create progress bar
    pbar = tqdm(desc="Fetching Douban ratings", unit="page")
    
    # Create a counter for session pages
    session_page_count = 0
    
    while has_next_page:
        # Check if we need to restart the browser session
        if session_page_count >= MAX_PAGES_PER_SESSION:
            logger.info(f"Reached maximum pages per session ({MAX_PAGES_PER_SESSION}), restarting browser")
            # Close current browser
            browser.quit()
            
            # Add a significant delay before starting a new session
            random_sleep(30, 60)
            
            # Create a new browser and login again
            browser = setup_browser()
            login_to_douban(browser)
            
            # Reset session counter
            session_page_count = 0
        
        # Construct URL with page parameter
        url = f"https://movie.douban.com/people/{user_id}/collect?start={(page-1)*15}&sort=time&rating=all&filter=all&mode=grid"
        
        # Random delay before loading the page
        random_sleep(DOUBAN_MIN_PAGE_DELAY, DOUBAN_MAX_PAGE_DELAY)
        
        browser.get(url)
        
        # Wait for page to load
        try:
            WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".grid-view"))
            )
            
            # Random scrolling to mimic human behavior
            scroll_height = browser.execute_script("return document.body.scrollHeight")
            for _ in range(random.randint(2, 5)):  # Random number of scroll actions
                scroll_position = random.randint(100, max(200, scroll_height - 200))
                browser.execute_script(f"window.scrollTo(0, {scroll_position});")
                time.sleep(random.uniform(0.5, 1.5))  # Random delay between scrolls
                
        except TimeoutException:
            logger.warning(f"Timeout loading page {page}, retrying with backoff...")
            backoff_time = exponential_backoff(0)
            time.sleep(backoff_time)
            browser.refresh()
            time.sleep(2)
            continue
        
        # Parse the page
        soup = BeautifulSoup(browser.page_source, 'html.parser')
        movie_items = soup.select(".grid-view .item")
        
        if not movie_items:
            logger.info(f"No movies found on page {page}, ending search")
            break
        
        for item in movie_items:
            try:
                # Extract movie info
                title_elem = item.select_one(".title a")
                title = title_elem.text.strip()
                douban_url = title_elem["href"]
                douban_id = re.search(r"subject/(\d+)/", douban_url).group(1)
                
                # Extract rating
                rating_elem = item.select_one(".rating")
                if not rating_elem:
                    # Skip unrated items
                    continue
                    
                # Extract rating value from class name
                # Rating classes are like "rating1-t", "rating2-t", etc.
                # where the digit represents the rating from 1 to 5
                rating_class = rating_elem.select_one("span")["class"][0]
                rating_value = int(rating_class[6])  # Extract number from class name
                
                # Ensure rating is within the 1-5 range
                if rating_value < 1 or rating_value > 5:
                    logger.warning(f"Invalid rating value {rating_value} for movie {title}, skipping")
                    continue
                
                # Extract year and director from info text
                info_elem = item.select_one(".info .intro")
                info_text = info_elem.text.strip()
                
                # Try to extract year from title or info
                year_match = re.search(r"\((\d{4})\)", title) or re.search(r"\s(\d{4})\s", info_text)
                year = year_match.group(1) if year_match else None
                
                # Random delay before visiting movie page to extract IMDb ID
                random_sleep(DOUBAN_MIN_MOVIE_DELAY, DOUBAN_MAX_MOVIE_DELAY)
                
                # Extract IMDb ID from the movie page
                imdb_id = extract_imdb_id(browser, douban_url)
                
                # Add to ratings list
                ratings.append({
                    "title": title,
                    "douban_id": douban_id,
                    "douban_url": douban_url,
                    "imdb_id": imdb_id,  # Add the IMDb ID if found
                    "rating": rating_value,
                    "year": year,
                    "info": info_text
                })
                
            except Exception as e:
                logger.warning(f"Error processing movie item: {e}")
                continue
        
        # Check for next page
        next_link = soup.select_one(".next a")
        has_next_page = next_link is not None
        
        # Increment counters
        page += 1
        session_page_count += 1
        pbar.update(1)
    
    pbar.close()
    return ratings

def export_douban_ratings():
    """Main function to export Douban ratings with anti-scraping measures."""
    ensure_data_dir()
    
    if not DOUBAN_USERNAME or not DOUBAN_PASSWORD:
        logger.error("Douban credentials not found in .env file")
        return False
    
    browser = None
    try:
        # Set up browser with anti-scraping measures
        browser = setup_browser()
        
        # Login to Douban
        login_to_douban(browser)
        
        # Get user ID
        user_id = get_user_id(browser)
        
        logger.info(f"Fetching ratings for Douban user {user_id}")
        ratings = fetch_movie_ratings(browser, user_id)
        
        logger.info(f"Found {len(ratings)} rated movies on Douban")
        
        # Save ratings to file
        save_json(ratings, DOUBAN_EXPORT_PATH)
        
        return True
        
    except Exception as e:
        logger.error(f"Error exporting Douban ratings: {e}")
        return False
        
    finally:
        if browser:
            browser.quit()

if __name__ == "__main__":
    if export_douban_ratings():
        print(f"Successfully exported Douban ratings to {DOUBAN_EXPORT_PATH}")
    else:
        print("Failed to export Douban ratings. Check the log for details.") 