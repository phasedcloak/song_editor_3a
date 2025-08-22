#!/usr/bin/env python3
"""
Cross-platform build script for Song Editor 3
Builds executables for macOS, Windows, and Linux
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors"""
    print(f"\n🔄 {description}...")
    print(f"Command: {cmd}")
    
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"Error: {e}")
        print(f"Output: {e.stdout}")
        print(f"Error: {e.stderr}")
        return False

def build_for_platform(platform_name, spec_file):
    """Build executable for a specific platform"""
    print(f"\n🚀 Building for {platform_name}...")
    
    # Clean previous builds
    if os.path.exists("dist"):
        run_command("rm -rf dist", f"Cleaning {platform_name} build artifacts")
    if os.path.exists("build"):
        run_command("rm -rf build", f"Cleaning {platform_name} build artifacts")
    
    # Build the executable
    if run_command(f"pyinstaller {spec_file}", f"Building {platform_name} executable"):
        print(f"✅ {platform_name} build completed successfully!")
        return True
    else:
        print(f"❌ {platform_name} build failed!")
        return False

def main():
    """Main build function"""
    print("🎵 Song Editor 3 - Cross-Platform Build Script")
    print("=" * 50)
    
    # Detect current platform
    current_platform = platform.system().lower()
    print(f"Current platform: {current_platform}")
    
    # Define build targets
    builds = {
        "macos": "song_editor_3_working_complete.spec",
        "windows": "song_editor_3_windows.spec", 
        "linux": "song_editor_3_linux.spec"
    }
    
    # Build for current platform first
    if current_platform in builds:
        print(f"\n🎯 Building for current platform: {current_platform}")
        if build_for_platform(current_platform, builds[current_platform]):
            print(f"✅ {current_platform} build successful!")
        else:
            print(f"❌ {current_platform} build failed!")
            return False
    
    # Build for other platforms if possible
    for platform_name, spec_file in builds.items():
        if platform_name != current_platform:
            print(f"\n⚠️  Cross-compilation for {platform_name} requires:")
            print(f"   - {platform_name} build environment")
            print(f"   - Cross-compilation tools")
            print(f"   - Platform-specific dependencies")
            print(f"   Skipping {platform_name} build...")
    
    print("\n🎉 Build process completed!")
    print("\n📁 Executables created in 'dist/' directory:")
    
    if os.path.exists("dist"):
        for item in os.listdir("dist"):
            if os.path.isfile(os.path.join("dist", item)):
                size = os.path.getsize(os.path.join("dist", item)) / (1024 * 1024)
                print(f"   - {item} ({size:.1f} MB)")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
