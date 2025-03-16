#!/usr/bin/env python3
import os
import json
import re
from bs4 import BeautifulSoup

# Configuration variables
DEBUG_LOG_DIR = 'debug_logs'
IMDB_EXPORT_PATH = 'imdb_ratings_from_debug.json'
MAX_MOVIES = 25

def extract_movie_data_from_debug_logs():
    """Extract movie data from debug log files."""
    print(f"Extracting the first {MAX_MOVIES} movies from debug logs...")
    
    # Find the most recent batch file
    batch_files = []
    for file in os.listdir(DEBUG_LOG_DIR):
        if file.startswith('batch_') and file.endswith('.html'):
            batch_files.append(os.path.join(DEBUG_LOG_DIR, file))
    
    if not batch_files:
        print("No batch debug files found.")
        return []
    
    # Sort by modification time (most recent first)
    batch_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    most_recent_batch = batch_files[0]
    print(f"Using most recent debug file: {most_recent_batch}")
    
    # Read the HTML file
    with open(most_recent_batch, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Create BeautifulSoup object
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract movie data
    ratings = []
    
    # Find all title links
    title_links = soup.select('a[aria-label^="View title page for"]')
    print(f"Found {len(title_links)} title links in the debug file")
    
    # Process each title link
    for link in title_links[:MAX_MOVIES]:
        try:
            # Get title from aria-label
            aria_label = link.get('aria-label', '')
            title_match = re.match(r'View title page for (.+)', aria_label)
            title = title_match.group(1) if title_match else link.text.strip()
            
            # Get the parent container
            container = link
            while container and not container.select('span[class*="dli-title-metadata-item"]') and container.name != 'body':
                container = container.parent
            
            if not container:
                print(f"No container found for {title}")
                continue
            
            # Get year
            year = None
            year_elements = container.select('span[class*="dli-title-metadata-item"]')
            for element in year_elements:
                text = element.text.strip()
                # Year is typically the first metadata item
                if re.match(r'^(19|20)\d{2}', text):
                    year = text[:4]  # Get only the year part
                    break
            
            # Get IMDb ID from link href
            href = link.get('href', '')
            imdb_id_match = re.search(r'/title/(tt\d+)', href)
            imdb_id = imdb_id_match.group(1) if imdb_id_match else None
            
            # Find rating - look for button with aria-label="Your rating: X"
            rating = None
            rating_buttons = container.select('button[aria-label^="Your rating:"]')
            if rating_buttons:
                rating_label = rating_buttons[0].get('aria-label', '')
                rating_match = re.search(r'Your rating:\s*(\d+)', rating_label)
                if rating_match and rating_match.group(1):
                    rating = int(rating_match.group(1))
                    
            # Only add if all required data is present
            if title and imdb_id and rating is not None and year:
                imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
                
                movie_data = {
                    "title": title,
                    "imdb_url": imdb_url,
                    "imdb_id": imdb_id,
                    "year": year,
                    "rating": rating
                }
                
                ratings.append(movie_data)
                print(f"Added: {title} ({year}) - Rating: {rating}/10")
            else:
                print(f"Missing required data for {title} - "
                      f"imdbId: {'YES' if imdb_id else 'NO'}, "
                      f"rating: {rating if rating is not None else 'NO'}, "
                      f"year: {year if year else 'NO'}")
                
        except Exception as e:
            print(f"Error processing title: {e}")
    
    print(f"\nExtracted {len(ratings)} movies with complete data")
    return ratings

def save_ratings_to_file(ratings):
    """Save the extracted ratings to a JSON file."""
    try:
        with open(IMDB_EXPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
        
        print(f"Successfully saved {len(ratings)} ratings to {IMDB_EXPORT_PATH}")
        
        # Verify file was written correctly
        if os.path.exists(IMDB_EXPORT_PATH):
            file_size = os.path.getsize(IMDB_EXPORT_PATH)
            print(f"File exists with size: {file_size} bytes")
            return True
        else:
            print(f"ERROR: File {IMDB_EXPORT_PATH} does not exist after save!")
            return False
    except Exception as e:
        print(f"Error during save: {e}")
        return False

def main():
    """Main function to extract and save movie data."""
    print("Starting extraction from debug logs...")
    
    # Create debug_logs directory if it doesn't exist
    if not os.path.exists(DEBUG_LOG_DIR):
        print(f"Warning: Debug logs directory '{DEBUG_LOG_DIR}' not found.")
        return
    
    # Extract ratings from debug logs
    ratings = extract_movie_data_from_debug_logs()
    
    # Save ratings to file
    if ratings:
        save_success = save_ratings_to_file(ratings)
        if save_success:
            print("Test completed successfully!")
        else:
            print("Failed to save ratings to file.")
    else:
        print("No ratings extracted. Check the debug logs for more information.")

if __name__ == "__main__":
    main() 