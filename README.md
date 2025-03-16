# Douban to IMDb

A Python tool to export your Douban movie ratings to IMDb-compatible format.

## Features

- Export all your Douban movie ratings
- Automatically match Douban movies to IMDb IDs
- Support for manual matching of difficult cases
- Ability to resume from previous exports
- Handles Douban's detection mechanisms
- Multiple recovery strategies for finding IMDb IDs

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/douban2imdb.git
cd douban2imdb
```

2. Install requirements:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (optional):
```bash
cp .env.sample .env
# Edit .env file with your preferred settings
```

4. Make sure you have Chrome installed (for the Selenium web driver).

## Usage

### Export Your Douban Ratings

```bash
python src/douban_export.py
```

This will:
1. Open a Chrome browser
2. Ask you to log in to Douban manually
3. Extract your user ID
4. Scrape all your movie ratings
5. Match each movie to its IMDb ID
6. Save the results to `data/douban_ratings.json`

### Fill Missing IMDb IDs

If some movies couldn't be matched automatically:

```bash
python src/douban_export.py --fill-missing-imdb
```

### Manually Match Difficult Cases

For movies that can't be matched automatically:

```bash
python src/manual_imdb_match.py
```

This interactive tool will:
1. Show you each movie missing an IMDb ID
2. Let you search IMDb directly
3. Allow you to input the correct IMDb ID

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

See `.env.sample` for all available options.

## License

MIT

## Acknowledgements

- [Douban](https://movie.douban.com/) for the movie data
- [IMDb](https://www.imdb.com/) for movie identifiers 