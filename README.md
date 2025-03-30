# Douban to IMDb

A Python tool to migrate your Douban movie ratings to your IMDb account.

## Features

### Core Features
- **Douban Export**: Automatically exports your complete movie rating history
- **IMDb Import**: Matches movies and imports ratings to your IMDb account
- **Smart Matching**: Uses multiple strategies to find correct IMDb matches
- **Manual Review**: User-friendly interface for reviewing uncertain matches

### Additional Features
- **TV Show Support**: Properly handles TV series with multiple seasons
- **Rating Conversion**: Converts Douban's 5-star to IMDb's 10-star scale
- **Resume Support**: Can continue from where it left off if interrupted
- **Proxy Support**: Optional proxy configuration for better reliability


## Requirements
- Python 3.8 or higher

## Installation

1. Clone this repository:
```bash
git clone https://github.com/tylerxiety/douban2imdb.git
cd douban2imdb
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install requirements:
```bash
pip install -r requirements.txt
```

> Note: The `venv` folder is ignored by git and won't be included in the repository.

4. Set up environment variables (optional):
```bash
cp .env.example .env
# Edit .env file with your preferred settings
```

5. Make sure you have Chrome installed (for the Selenium web driver). And you know your Douban ID.

## Usage

The complete migration process involves these steps:

1. Exporting Douban ratings
2. (Optional) Exporting IMDb ratings
3. Preparing a migration plan
4. Executing the migration to IMDb

You can run each step separately or use the main script to run all steps in sequence.

### Using the main script (recommended)

The main script automatically runs all steps in the correct order:

```bash
python src/main.py
```

You can also run specific steps:

```bash
python src/main.py --step export_douban  # Only export Douban ratings
python src/main.py --step export_imdb     # Only export IMDb ratings (optional)
python src/main.py --step prepare         # Only prepare the migration plan
python src/main.py --step migrate         # Only execute the migration (select Option 2)
```

### Step 1: Export Your Douban Ratings

```bash
python src/douban_export.py
```

This will:
1. Open a Chrome browser
2. Ask you to log in to Douban manually
3. Automatically detect your user ID (or ask you to provide it if detection fails)
4. Scrape all your movie ratings
5. Extract IMDb IDs directly from the Douban movie pages when available
6. Save the results to `data/douban_ratings.json`

#### Fill Missing IMDb IDs

If some movies couldn't be matched automatically:

```bash
python src/douban_export.py --fill-missing-imdb
```

#### Manually Match Difficult Cases

For movies that can't be matched automatically:

```bash
python src/manual_imdb_match.py
```

This interactive tool will:
1. Show you each movie missing an IMDb ID
2. Let you search IMDb directly
3. Allow you to input the correct IMDb ID

### Step 2: (Optional) Export Your IMDb Ratings

```bash
python src/imdb_export.py
```

This optional step will:
1. Open a Chrome browser
2. Ask you to log in to IMDb manually
3. Export your existing IMDb ratings to `data/imdb_ratings.json`

This helps speed up the migration process by identifying movies you've already rated on IMDb so they can be skipped. If you skip this step, the migration will still work but will need to check if each movie is already rated during the migration process.

### Step 3: Prepare Migration Plan

Generate a plan for migrating your ratings to IMDb:

```bash
python src/prepare_migration.py
```

This creates a migration plan that:
- Identifies movies to migrate
- Groups TV shows with multiple seasons
- Averages ratings for TV shows
- Handles duplicate entries

### Step 4: Execute Migration to IMDb

Finally, execute the migration to update your IMDb ratings:

```bash
python src/migrate.py --execute-plan
```

The migration script will:
1. Open a Chrome browser
2. Ask you to log in to IMDb manually
3. Process each movie in your migration plan
4. Rate the movies on IMDb with your Douban ratings
5. Save migration progress to allow resuming if interrupted

#### Advanced Migration Options

You can customize the migration process with several options:

```bash
# Test mode with limited number of movies
python src/migrate.py --execute-plan --max-movies 5 --test-mode

# With proxy server
python src/migrate.py --execute-plan --proxy "http://user:pass@host:port"

# With custom timeout and retries
python src/migrate.py --execute-plan --timeout 120 --retries 7

# Enable speed mode for faster processing
python src/migrate.py --execute-plan --speed-mode
```

## TV Show Handling

TV shows are properly handled by:

1. Identifying related seasons based on title similarity
2. Averaging ratings across all seasons
3. Using the IMDb ID from the first season on Douban page as the main IMDb ID
4. Redirecting from episode pages to main show pages automatically

## Troubleshooting

If you encounter connection issues:

1. Try increasing timeout: `--timeout 180`
2. Increase retries: `--retries 10`
3. Use a proxy server:
   ```
   # Add to your .env file:
   PROXY=http://user:pass@host:port
   
   # Or specify on command line:
   python src/migrate.py --execute-plan --proxy "http://user:pass@host:port"
   ```
4. Enable speed mode for faster loading: `--speed-mode`
5. Run in test mode to see detailed diagnostics: `--test-mode`

## Configuration

The script behavior can be modified through environment variables in your `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `DOUBAN_EXPORT_PATH` | Path to save ratings | `data/douban_ratings.json` |
| `DEBUG_MODE` | Enable verbose logging | `False` | 
| `THROTTLING_ENABLED` | Enable request throttling | `False` |
| `FAST_MODE` | Skip non-essential operations for speed | `True` |
| `BROWSER_MAX_INIT_ATTEMPTS` | Number of browser init retry attempts | `3` |
| `CHROME_PATH` | Optional path to Chrome binary | System default |
| `MIN_PAGE_DELAY` | Minimum delay between page loads (seconds) | `0.0` |
| `MAX_PAGE_DELAY` | Maximum delay between page loads (seconds) | `0.2` |
| `START_PAGE` | Starting page number for ratings | `1` |
| `MAX_PAGES` | Maximum pages to process (0 for unlimited) | `0` |
| `PROXY` | Proxy server in format http://user:pass@host:port | None |

See `.env.sample` for all available options.

## License

MIT

## Acknowledgements

- [Douban](https://movie.douban.com/)
- [IMDb](https://www.imdb.com/)