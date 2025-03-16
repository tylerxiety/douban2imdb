"""
Main script to run the entire Douban to IMDb rating migration process.
"""
import os
import logging
import argparse
from dotenv import load_dotenv

from utils import logger, ensure_data_dir
from douban_export import export_douban_ratings
from imdb_export import export_imdb_ratings
from prepare_migration import prepare_migration_plan
from migrate import migrate_ratings

def main():
    """
    Run the Douban to IMDb rating migration process.
    """
    # Set up command line arguments
    parser = argparse.ArgumentParser(description="Migrate movie ratings from Douban to IMDb")
    parser.add_argument("--step", type=str, choices=["all", "export_douban", "export_imdb", "prepare", "migrate"],
                        default="all", help="Which step of the process to run")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    
    # Set logging level based on verbosity
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Make sure data directory exists
    ensure_data_dir()
    
    # Load environment variables
    load_dotenv()
    
    # Check if .env file exists with required credentials
    if not os.path.exists(".env"):
        print("Warning: .env file not found. Please create one with your credentials.")
        print("See .env.example for reference.")
    
    # Run the selected step(s)
    if args.step == "export_douban" or args.step == "all":
        logger.info("Step 1: Exporting Douban ratings")
        export_douban_ratings()
    
    if args.step == "export_imdb" or args.step == "all":
        logger.info("Step 2: Exporting IMDb ratings")
        export_imdb_ratings()
    
    if args.step == "prepare" or args.step == "all":
        logger.info("Step 3: Preparing migration plan")
        prepare_migration_plan()
    
    if args.step == "migrate" or args.step == "all":
        logger.info("Step 4: Migrating ratings to IMDb")
        migrate_ratings()
    
    logger.info("Migration process complete!")

if __name__ == "__main__":
    main() 