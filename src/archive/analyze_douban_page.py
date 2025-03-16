"""
Utility script to analyze the Douban ratings page structure.
This helps identify the correct CSS selectors to extract ratings.
"""
import os
import re
from bs4 import BeautifulSoup

def analyze_douban_page():
    """Analyze the saved Douban ratings page HTML to find the correct selectors."""
    # Check if the HTML file exists
    html_file = "douban_ratings_page.html"
    if not os.path.exists(html_file):
        print(f"File {html_file} not found. Run the direct_douban_export.py script first.")
        return
    
    # Load and parse the HTML
    print(f"Loading {html_file}...")
    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    print(f"Parsing complete. HTML size: {len(html_content)} bytes")
    
    # Check the page title to confirm it's a Douban ratings page
    title = soup.title.text if soup.title else "No title found"
    print(f"Page title: {title}")
    
    # Find all movie items
    items = soup.select(".grid-view .item")
    print(f"Found {len(items)} movie items")
    
    if len(items) == 0:
        print("\nERROR: No movie items found with selector '.grid-view .item'")
        print("Trying alternate selectors...")
        
        # Try alternative selectors
        alternate_selectors = [
            ".list-view .item",
            ".list .item",
            ".grid-view li",
            "#content .item",
            ".subject-item"
        ]
        
        for selector in alternate_selectors:
            alt_items = soup.select(selector)
            print(f"Selector '{selector}': {len(alt_items)} items found")
            
            if len(alt_items) > 0:
                print(f"\nFound items with selector '{selector}'. First item HTML:")
                print(alt_items[0].prettify()[:500] + "...")
        
        # Look for any list structures
        list_elements = soup.select("ul, ol")
        print(f"\nFound {len(list_elements)} list elements in the document")
        
        # Look for common item structures
        movie_related = soup.find_all(text=re.compile("电影|评分|星|rating|movie"))
        print(f"Found {len(movie_related)} elements containing movie-related text")
        
        print("\nTry checking the HTML file manually to identify the correct structure")
        return
    
    # If items found, analyze the first one in detail
    print("\n=== First Movie Item Analysis ===")
    first_item = items[0]
    print(first_item.prettify())
    
    # Find title
    title_elem = first_item.select_one(".title a")
    if title_elem:
        print(f"\nTitle found: {title_elem.text.strip()}")
        print(f"URL: {title_elem.get('href')}")
    else:
        print("\nTitle element not found with selector '.title a'")
        # Try alternative selectors for title
        alt_title_selectors = [".item-title", "h2", "h3", ".info a", "a.title"]
        for selector in alt_title_selectors:
            alt_title = first_item.select_one(selector)
            if alt_title:
                print(f"Alternative title found with '{selector}': {alt_title.text.strip()}")
    
    # Find rating elements
    print("\n=== Rating Elements ===")
    # Try standard rating class
    rating_elem = first_item.select_one(".rating")
    if rating_elem:
        print("Rating element found with '.rating'")
        print(rating_elem.prettify())
        
        # Check for span with class pattern
        rating_spans = rating_elem.select("span")
        print(f"Found {len(rating_spans)} span elements within rating")
        
        for i, span in enumerate(rating_spans):
            print(f"Span {i+1} classes: {span.get('class')}")
            if span.get('class') and any('rating' in c for c in span.get('class')):
                print(f"Rating class found: {span.get('class')}")
    else:
        print("No rating element found with '.rating'")
    
    # Check for stars
    star_full = first_item.select(".star-full")
    star_half = first_item.select(".star-half")
    if star_full or star_half:
        print(f"Stars found: {len(star_full)} full, {len(star_half)} half")
    
    # Look for elements containing rating numbers
    rating_numbers = first_item.find_all(text=re.compile(r"[1-5]星|[1-5]\s*stars|rated\s*[1-5]|rating.*?[1-5]", re.IGNORECASE))
    if rating_numbers:
        print("\nText containing rating numbers:")
        for text in rating_numbers:
            print(f"  - '{text.strip()}'")
    
    # Find all class names that might contain ratings
    all_classes = []
    for tag in first_item.find_all(lambda tag: tag.has_attr('class')):
        all_classes.extend(tag.get('class'))
    
    rating_classes = [cls for cls in all_classes if 'rat' in cls.lower() or 'star' in cls.lower()]
    if rating_classes:
        print("\nClasses related to ratings:")
        for cls in rating_classes:
            print(f"  - {cls}")
    
    print("\n=== HTML Classes Summary ===")
    class_counts = {}
    for cls in all_classes:
        class_counts[cls] = class_counts.get(cls, 0) + 1
    
    for cls, count in sorted(class_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"{cls}: {count} occurrences")
    
    # Recommendations
    print("\n=== Recommendations ===")
    print("Based on this analysis, update the selectors in src/direct_douban_export.py")
    print("Look for the rating elements in the HTML and modify the code to extract them correctly")
    print("The script will need to be updated to match the current structure of the Douban ratings page")

if __name__ == "__main__":
    analyze_douban_page() 