# Improved Migration Script Instructions

## Summary of Improvements
We've made significant improvements to the migration script to handle TV shows and improve connection reliability:

1. **Better TV Show Handling**:
   - TV shows with multiple seasons are now properly identified and grouped
   - Season ratings are averaged to provide a single rating for each TV show
   - The main series IMDb ID from the first season is used for all seasons

2. **Improved Connection Handling**:
   - Added proxy support via command line or .env file
   - Better error handling with timeouts and retries
   - More robust page loading detection with fallbacks
   - Improved browser setup for better IMDb compatibility


## How to Run the Script

### Basic Usage:
```bash
# Create a migration plan
python src/prepare_migration.py

# Execute migration plan
python src/migrate.py --execute-plan
```

### With Options:
```bash
# Test mode with 5 movies
python src/migrate.py --execute-plan --max-movies 5 --test-mode

# With proxy server
python src/migrate.py --execute-plan --proxy "http://user:pass@host:port"

# With custom timeout and retries
python src/migrate.py --execute-plan --timeout 120 --retries 7
```

### Using a Proxy
If IMDb is blocking your access due to regional restrictions or rate limiting, you can use a proxy:

1. Add to your .env file:
   ```
   PROXY=http://user:pass@host:port
   ```

2. Or specify on command line:
   ```
   python src/migrate.py --execute-plan --proxy "http://user:pass@host:port"
   ```

## Troubleshooting
If you encounter connection issues:

1. Try increasing timeout: `--timeout 180`
2. Increase retries: `--retries 10`
3. Use a proxy server as shown above
4. Enable speed mode for faster loading: `--speed-mode`
5. Run in test mode to see detailed diagnostics: `--test-mode`

## TV Show Handling
TV shows are now properly handled by:

1. Identifying related seasons based on title similarity
2. Averaging ratings across all seasons
3. Using the main IMDb ID from the first season for all ratings
4. Redirecting from episode pages to main show pages automatically
