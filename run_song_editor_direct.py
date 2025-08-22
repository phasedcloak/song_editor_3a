#!/usr/bin/env python3
"""
Direct launcher for Song Editor 3
This script runs the application directly without needing to build an executable.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Main entry point for Song Editor 3"""
    try:
        # Import and run the main application
        from song_editor.app import main as app_main
        app_main()
    except ImportError as e:
        print(f"Error importing Song Editor 3: {e}")
        print("Please ensure all dependencies are installed:")
        print("pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"Error running Song Editor 3: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
