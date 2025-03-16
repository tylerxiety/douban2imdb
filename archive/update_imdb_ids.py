#!/usr/bin/env python3
import os
import json
import re
import time
import random
import argparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import chromedriver_autoinstaller
from tqdm import tqdm

# Paths
DOUBAN_RATINGS_PATH = "data/douban_ratings.json"
UPDATED_RATINGS_PATH = "data/douban_ratings_updated.json"

def setup_browser(headless=True):
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
    
    # Always use headless mode for this script
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Add user agent to avoid detection
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    # Create browser
    browser = webdriver.Chrome(options=chrome_options)
    
    # Set a reasonable timeout
    browser.set_page_load_timeout(15)
    
    # Set script timeout - for executeScript calls
    browser.set_script_timeout(15)
    
    print("Browser set up with performance optimizations")
    return browser

def extract_imdb_id(browser, douban_url):
    """Extract IMDb ID from Douban movie page."""
    try:
        # Add a random but shorter delay to avoid detection
        time.sleep(random.uniform(0.2, 0.7))
        
        try:
            # Set a page load strategy and timeout
            browser.set_page_load_timeout(10)
            browser.get(douban_url)
        except TimeoutException:
            # If timeout occurs during page load, try to extract from partial page
            print(f"Page load timeout for {douban_url}, attempting extraction from partial page")
            pass
        except Exception as e:
            print(f"Error loading page {douban_url}: {e}")
            return None
            
        # Try direct methods first using optimized JavaScript
        try:
            # Use an optimized JavaScript to extract the IMDb ID (faster than parsing)
            js_script = """
            // Find any IMDb ID in the page content (faster and more thorough)
            var infoText = document.body.textContent;
            var imdbMatches = infoText.match(/IMDb:\\s*(tt\\d+)/i);
            if (imdbMatches) return imdbMatches[1];
            
            // Look for IMDb links - more reliable on Douban
            var imdbLinks = document.querySelectorAll('a[href*="imdb.com/title/"]');
            for (var i = 0; i < imdbLinks.length; i++) {
                var linkMatch = imdbLinks[i].href.match(/title\\/(tt\\d+)/);
                if (linkMatch) return linkMatch[1];
            }
            
            // Check specifically in the info section
            var infoSection = document.getElementById('info');
            if (infoSection) {
                var infoLinks = infoSection.querySelectorAll('a');
                for (var i = 0; i < infoLinks.length; i++) {
                    if (infoLinks[i].href.includes('imdb.com')) {
                        var match = infoLinks[i].href.match(/title\\/(tt\\d+)/);
                        if (match) return match[1];
                    }
                    // Sometimes Douban has the IMDb ID as plain text
                    if (infoLinks[i].textContent.match(/tt\\d+/)) {
                        return infoLinks[i].textContent.match(/tt\\d+/)[0];
                    }
                }
            }
            
            return null;
            """
            imdb_id = browser.execute_script(js_script)
            if imdb_id:
                return imdb_id
            
            # More aggressive search if JavaScript didn't find anything
            js_fallback = """
            // Look for any tt pattern in the page that looks like an IMDb ID
            var allText = document.body.textContent;
            var ttMatches = allText.match(/tt\\d{7,8}/);
            return ttMatches ? ttMatches[0] : null;
            """
            imdb_id = browser.execute_script(js_fallback)
            if imdb_id:
                return imdb_id
                
        except Exception as e:
            print(f"JavaScript extraction failed: {e}")
            
        # Fallback to BeautifulSoup only if JavaScript methods fail
        return extract_imdb_id_from_html(browser.page_source)
            
    except Exception as e:
        print(f"Error extracting IMDb ID: {e}")
        return None

def extract_imdb_id_from_html(html_content):
    """Extract IMDb ID from HTML content using BeautifulSoup."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # More aggressive pattern matching for IMDb IDs anywhere in the HTML
        html_text = str(soup)
        imdb_id_match = re.search(r'(tt\d{7,8})', html_text)
        if imdb_id_match:
            return imdb_id_match.group(1)
        
        # Look for IMDb ID in the info section (original method)
        info_section = soup.select_one("#info")
        if info_section:
            # Look for IMDb link or ID in the text
            imdb_text = info_section.text
            imdb_match = re.search(r'IMDb:\s*(tt\d+)', imdb_text)
            if imdb_match:
                return imdb_match.group(1)
            
            # Look for IMDb link
            imdb_link = info_section.select_one('a[href*="imdb.com/title/"]')
            if imdb_link:
                link_match = re.search(r'title/(tt\d+)', imdb_link['href'])
                if link_match:
                    return link_match.group(1)
        
        # No IMDb ID found
        return None
        
    except Exception as e:
        print(f"Error extracting IMDb ID from HTML: {e}")
        return None

def update_imdb_ids(max_movies=None, start_index=0):
    """Update IMDb IDs for Douban movies."""
    # Load existing ratings
    with open(DOUBAN_RATINGS_PATH, 'r', encoding='utf-8') as f:
        ratings = json.load(f)
    
    # Filter movies without IMDb IDs
    movies_without_imdb = [movie for movie in ratings if 'imdb_id' not in movie]
    total_movies = len(ratings)
    missing_imdb_ids = len(movies_without_imdb)
    
    print(f"Total Douban movies: {total_movies}")
    print(f"Movies without IMDb ID: {missing_imdb_ids} ({missing_imdb_ids/total_movies*100:.2f}%)")
    
    if max_movies:
        movies_to_update = movies_without_imdb[start_index:start_index+max_movies]
        print(f"Processing {len(movies_to_update)} movies starting from index {start_index}")
    else:
        movies_to_update = movies_without_imdb[start_index:]
        print(f"Processing all {len(movies_to_update)} remaining movies without IMDb IDs")
    
    if not movies_to_update:
        print("No movies to update. Exiting.")
        return
    
    # Performance optimization: use a more efficient browser setup
    browser = setup_browser(headless=True)
    
    try:
        # Update IMDb IDs for each movie
        updated_count = 0
        failed_count = 0
        
        for i, movie in enumerate(tqdm(movies_to_update, desc="Updating IMDb IDs")):
            douban_url = movie.get("douban_url")
            if not douban_url:
                continue
                
            print(f"\nProcessing {i+1}/{len(movies_to_update)}: {movie.get('title')} ({movie.get('year')})")
            
            # Try up to 2 times to extract the IMDb ID
            for attempt in range(2):
                imdb_id = extract_imdb_id(browser, douban_url)
                if imdb_id:
                    # Find the movie in the original ratings list
                    for original_movie in ratings:
                        if original_movie.get("douban_id") == movie.get("douban_id"):
                            original_movie["imdb_id"] = imdb_id
                            updated_count += 1
                            break
                    
                    print(f"  ✓ Found IMDb ID: {imdb_id}")
                    break
                elif attempt == 0:  # Try one more time before giving up
                    print(f"  Retrying extraction... (attempt {attempt+2}/2)")
                    # Clear browser cache before retrying
                    browser.execute_script("window.localStorage.clear();")
                    browser.execute_script("window.sessionStorage.clear();")
                    browser.delete_all_cookies()
                    time.sleep(1)  # Wait a bit longer before retry
                else:
                    failed_count += 1
                    print(f"  ✗ No IMDb ID found after {attempt+1} attempts")
            
            # Save the updated ratings more frequently (every 5 movies)
            if (i + 1) % 5 == 0 or (i + 1) == len(movies_to_update):
                with open(UPDATED_RATINGS_PATH, 'w', encoding='utf-8') as f:
                    json.dump(ratings, f, ensure_ascii=False, indent=2)
                print(f"  Saved progress after {i+1} movies")
                
            # Brief pause between movies to avoid rate limiting
            if i < len(movies_to_update) - 1:
                time.sleep(random.uniform(0.1, 0.5))
        
        # Save the final updated ratings
        with open(UPDATED_RATINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
        
        # Count total IMDb IDs after update
        with_imdb_id = sum(1 for item in ratings if 'imdb_id' in item)
        
        print("\nUpdate completed!")
        print(f"Added IMDb IDs to {updated_count} movies")
        print(f"Failed to find IMDb IDs for {failed_count} movies")
        print(f"Total movies with IMDb ID: {with_imdb_id} ({with_imdb_id/total_movies*100:.2f}%)")
        print(f"Total movies without IMDb ID: {total_movies - with_imdb_id} ({(total_movies - with_imdb_id)/total_movies*100:.2f}%)")
        
        # Ask if the user wants to replace the original file
        if updated_count > 0:
            replace = input("\nReplace original douban_ratings.json with updated file? (y/n): ").lower() == 'y'
            if replace:
                import shutil
                # Make a backup first
                backup_path = f"{DOUBAN_RATINGS_PATH}.bak"
                shutil.copy2(DOUBAN_RATINGS_PATH, backup_path)
                print(f"Created backup at {backup_path}")
                
                # Replace the file
                shutil.copy2(UPDATED_RATINGS_PATH, DOUBAN_RATINGS_PATH)
                print(f"Replaced {DOUBAN_RATINGS_PATH} with updated data")
            else:
                print(f"Updated data saved to {UPDATED_RATINGS_PATH}")
    
    finally:
        # Close browser
        if browser:
            browser.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update IMDb IDs for Douban movies')
    parser.add_argument('--max', type=int, help='Maximum number of movies to process')
    parser.add_argument('--start', type=int, default=0, help='Starting index for processing')
    args = parser.parse_args()
    
    update_imdb_ids(max_movies=args.max, start_index=args.start) 