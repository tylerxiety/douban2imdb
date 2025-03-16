#!/bin/bash
# Cleanup script for Douban2IMDb

echo "Douban2IMDb Cleanup Utility"
echo "==========================="
echo ""

# Function to print colored text
print_colored() {
  local color=$1
  local text=$2
  
  case $color in
    "red") echo -e "\033[0;31m$text\033[0m" ;;
    "green") echo -e "\033[0;32m$text\033[0m" ;;
    "yellow") echo -e "\033[0;33m$text\033[0m" ;;
    "blue") echo -e "\033[0;34m$text\033[0m" ;;
  esac
}

# Count files
debug_count=$(find debug_logs -type f | wc -l)
log_count=$(find logs -type f | wc -l)

print_colored "blue" "Found:"
echo "- $debug_count debug files in debug_logs/"
echo "- $log_count log files in logs/"
echo ""

# Ask for confirmation
read -p "Clean debug logs? (y/n): " clean_debug
read -p "Clean log files? (y/n): " clean_logs
echo ""

# Clean debug logs if requested
if [[ "$clean_debug" == "y" || "$clean_debug" == "Y" ]]; then
  print_colored "yellow" "Cleaning debug logs..."
  rm -f debug_logs/*.html
  echo "✓ Debug logs cleaned"
fi

# Clean log files if requested
if [[ "$clean_logs" == "y" || "$clean_logs" == "Y" ]]; then
  print_colored "yellow" "Cleaning log files..."
  rm -f logs/*.log
  echo "✓ Log files cleaned"
fi

echo ""
print_colored "green" "Cleanup completed!" 