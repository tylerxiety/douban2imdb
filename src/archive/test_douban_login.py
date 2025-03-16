"""
Simple test script to attempt Douban login.
"""
import os
import time
import logging
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def main():
    # Get credentials and verify they're loaded correctly
    username = os.getenv("DOUBAN_USERNAME")
    password = os.getenv("DOUBAN_PASSWORD")
    
    # Debug information about environment variables
    logger.info("Environment variables content check:")
    logger.info(f"DOUBAN_USERNAME from env: '{username}'")
    
    # Check if the .env file exists
    if os.path.exists(".env"):
        logger.info(".env file exists, reading its contents:")
        try:
            with open(".env", "r") as f:
                env_content = f.read()
                # Don't log the entire content to avoid exposing passwords
                # Just check for presence of the variables
                if "DOUBAN_USERNAME=" in env_content:
                    logger.info("DOUBAN_USERNAME found in .env file")
                else:
                    logger.error("DOUBAN_USERNAME not found in .env file")
                if "DOUBAN_PASSWORD=" in env_content:
                    logger.info("DOUBAN_PASSWORD found in .env file")
                else:
                    logger.error("DOUBAN_PASSWORD not found in .env file")
        except Exception as e:
            logger.error(f"Error reading .env file: {e}")
    else:
        logger.error(".env file not found!")
    
    # Force load from .env file again to make sure
    dotenv_path = os.path.join(os.getcwd(), '.env')
    logger.info(f"Loading .env from: {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path, override=True)
    
    # Check if credentials are loaded now
    username = os.getenv("DOUBAN_USERNAME")
    password = os.getenv("DOUBAN_PASSWORD")
    logger.info(f"DOUBAN_USERNAME after explicit reload: '{username}'")
    
    if not username or not password:
        logger.error("Douban credentials not found in .env file")
        return
    
    logger.info(f"Using Douban credentials: {username} / [password hidden]")
    
    # Install ChromeDriver
    logger.info("Installing ChromeDriver...")
    chromedriver_autoinstaller.install()
    
    # Setup Chrome options
    logger.info("Setting up Chrome options...")
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    browser = None
    try:
        # Create browser
        logger.info("Creating Chrome browser...")
        browser = webdriver.Chrome(options=chrome_options)
        browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Navigate to Douban
        logger.info("Navigating to Douban...")
        browser.get("https://www.douban.com/")
        time.sleep(3)  # Wait for page to load
        
        # Check current URL and page content
        logger.info(f"Current URL: {browser.current_url}")
        
        # Look for login link
        try:
            logger.info("Looking for login link...")
            login_elements = browser.find_elements(By.XPATH, "//*[contains(text(), '登录')]")
            if login_elements:
                logger.info(f"Found {len(login_elements)} login elements")
                login_elements[0].click()
                logger.info("Clicked on login link")
                time.sleep(2)
            else:
                logger.warning("No login link found")
                
                # Try alternate login approach
                logger.info("Trying direct navigation to login page...")
                browser.get("https://accounts.douban.com/passport/login")
                time.sleep(3)
        except Exception as e:
            logger.error(f"Error finding login link: {e}")
            
        # Check if we're on a login page
        logger.info(f"Current URL after login attempt: {browser.current_url}")
        
        # Try to find login form elements
        try:
            logger.info("Looking for account tab...")
            account_tabs = browser.find_elements(By.CLASS_NAME, "account-tab-account")
            if account_tabs:
                logger.info("Found account tab, clicking...")
                account_tabs[0].click()
                time.sleep(1)
            
            # Look for username field
            logger.info("Looking for username field...")
            username_fields = browser.find_elements(By.ID, "username")
            
            if not username_fields:
                logger.info("Username field not found by ID, trying alternate selectors...")
                username_fields = browser.find_elements(By.NAME, "username")
                
            if username_fields:
                logger.info("Found username field, entering credentials...")
                username_fields[0].clear()
                username_fields[0].send_keys(username)
                time.sleep(1)
                
                # Look for password field
                logger.info("Looking for password field...")
                password_fields = browser.find_elements(By.ID, "password")
                
                if not password_fields:
                    logger.info("Password field not found by ID, trying alternate selectors...")
                    password_fields = browser.find_elements(By.NAME, "password")
                
                if password_fields:
                    logger.info("Found password field, entering password...")
                    password_fields[0].clear()
                    password_fields[0].send_keys(password)
                    time.sleep(1)
                    
                    # Look for login button with broader selectors
                    logger.info("Looking for login button...")
                    # Try multiple selectors for the login button
                    login_button_selectors = [
                        "//button[contains(@class, 'submit')]",
                        "//button[contains(@class, 'login')]", 
                        "//button[contains(text(), '登录')]",
                        "//input[@type='submit']",
                        "//a[contains(text(), '登录')]",
                        ".account-form-field-submit"
                    ]
                    
                    login_button = None
                    for selector in login_button_selectors:
                        logger.info(f"Trying selector: {selector}")
                        elements = []
                        try:
                            if selector.startswith("//"):
                                # XPath selector
                                elements = browser.find_elements(By.XPATH, selector)
                            elif selector.startswith("."):
                                # CSS selector
                                elements = browser.find_elements(By.CSS_SELECTOR, selector)
                            else:
                                # Default to CSS
                                elements = browser.find_elements(By.CSS_SELECTOR, selector)
                                
                            if elements:
                                logger.info(f"Found {len(elements)} elements with selector: {selector}")
                                login_button = elements[0]
                                break
                        except Exception as e:
                            logger.warning(f"Error with selector {selector}: {e}")
                    
                    # Dump page source for debugging
                    with open("login_page.html", "w", encoding="utf-8") as f:
                        f.write(browser.page_source)
                    logger.info("Saved page HTML to login_page.html for inspection")
                    
                    if login_button:
                        logger.info("Found login button, clicking...")
                        try:
                            login_button.click()
                        except Exception as e:
                            logger.error(f"Error clicking login button: {e}")
                            logger.info("Trying JavaScript click...")
                            browser.execute_script("arguments[0].click();", login_button)
                        
                        # Wait for QR code to appear
                        logger.info("Waiting for QR code to appear...")
                        time.sleep(5)
                        
                        # Pause for user to scan QR code with Douban mobile app
                        logger.info("⚠️ PLEASE SCAN THE QR CODE with your Douban mobile app ⚠️")
                        input("Press Enter AFTER you have successfully scanned the QR code and completed the login...")
                        
                        # Wait a bit more after confirmation
                        logger.info("Continuing after QR code scan...")
                        time.sleep(5)
                        
                        # Check current URL
                        logger.info(f"Current URL after QR code scan: {browser.current_url}")
                        
                        # Check if we're logged in
                        if "https://www.douban.com" in browser.current_url:
                            logger.info("Successfully logged in to Douban!")
                        else:
                            logger.warning("Login may have failed, checking page...")
                            
                            # Check for common elements that might indicate successful login
                            try:
                                profile_element = browser.find_elements(By.CSS_SELECTOR, ".nav-user-account")
                                if profile_element:
                                    logger.info("Found profile element, login successful!")
                                else:
                                    logger.warning("Profile element not found, login may have failed")
                            except Exception as e:
                                logger.error(f"Error checking login status: {e}")
                    else:
                        logger.error("Login button not found")
                else:
                    logger.error("Password field not found")
            else:
                logger.error("Username field not found")
        except Exception as e:
            logger.error(f"Error during login process: {e}")
        
        # Wait for manual inspection
        logger.info("Browser window will stay open for 30 seconds for manual inspection...")
        time.sleep(30)
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        if browser:
            logger.info("Closing browser...")
            browser.quit()

if __name__ == "__main__":
    main() 