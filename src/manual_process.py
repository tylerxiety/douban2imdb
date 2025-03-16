"""
Main script to guide users through the manual Douban to IMDb migration process.
"""
import os
import subprocess
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def display_header():
    """Display the application header."""
    clear_screen()
    print("=" * 60)
    print("             DOUBAN TO IMDB RATING MIGRATION TOOL               ")
    print("=" * 60)
    print("This tool helps you migrate your movie ratings from Douban to IMDb.")
    print("Due to anti-scraping measures, some steps require manual assistance.")

def check_env_file():
    """Check if the .env file exists and has required credentials."""
    if not os.path.exists(".env"):
        print("\n⚠️  WARNING: .env file not found!")
        print("Please create a .env file with your credentials. Use .env.example as a template.")
        input("\nPress Enter to continue...")
        return False
    
    with open(".env", "r") as f:
        env_content = f.read()
    
    # Check for placeholder values
    placeholders = [
        "your_douban_email_or_phone",
        "your_douban_password",
        "your_imdb_email",
        "your_imdb_password"
    ]
    
    for placeholder in placeholders:
        if placeholder in env_content:
            print(f"\n⚠️  WARNING: Found placeholder '{placeholder}' in .env file.")
            print("Please update .env with your actual credentials.")
            input("\nPress Enter to continue...")
            return False
    
    return True

def run_script(script_path):
    """Run a Python script and return its exit code."""
    try:
        result = subprocess.run(['python', script_path], check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False
    except Exception as e:
        print(f"Error running script: {e}")
        return False

def ensure_data_dir():
    """Ensure the data directory exists."""
    os.makedirs("data", exist_ok=True)

def main_menu():
    """Display the main menu and handle user choices."""
    while True:
        display_header()
        
        print("\nMAIN MENU:")
        print("1. Export Douban Ratings (with manual login)")
        print("2. Export IMDb Ratings (with manual login)")
        print("3. Create Migration Plan")
        print("4. Execute Migration")
        print("5. Full Migration Process")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ")
        
        if choice == "1":
            print("\nRunning Douban export script...")
            success = run_script("src/douban_export.py")
            if success:
                print("\n✅ Douban export completed successfully.")
            else:
                print("\n❌ Douban export failed. Check the logs for details.")
            input("\nPress Enter to continue...")
        
        elif choice == "2":
            print("\nRunning IMDb export script...")
            success = run_script("src/imdb_export.py")
            if success:
                print("\n✅ IMDb export completed successfully.")
            else:
                print("\n❌ IMDb export failed. Check the logs for details.")
            input("\nPress Enter to continue...")
        
        elif choice == "3":
            print("\nRunning Migration Plan creation...")
            # We'll use the function from migrate.py directly
            from migrate import create_migration_plan
            success = create_migration_plan()
            if success:
                print("\n✅ Migration plan created successfully.")
            else:
                print("\n❌ Failed to create migration plan. Check the logs for details.")
            input("\nPress Enter to continue...")
        
        elif choice == "4":
            print("\nExecuting Migration Plan...")
            # We'll use the function from migrate.py directly
            from migrate import execute_migration
            success = execute_migration()
            if success:
                print("\n✅ Migration executed successfully.")
            else:
                print("\n❌ Migration execution failed or was cancelled.")
            input("\nPress Enter to continue...")
        
        elif choice == "5":
            print("\nRunning Full Migration Process...")
            # Just launch the migrate.py script which has its own menu
            success = run_script("src/migrate.py")
            if success:
                print("\n✅ Migration process completed.")
            else:
                print("\n❌ Migration process encountered issues. Check the logs for details.")
            input("\nPress Enter to continue...")
        
        elif choice == "6":
            print("\nExiting application. Goodbye!")
            break
        
        else:
            print("\nInvalid choice. Please enter a number between 1 and 6.")
            time.sleep(1)

if __name__ == "__main__":
    ensure_data_dir()
    check_env_file()
    main_menu() 