"""
Quick Start Uploader
Opens everything you need to upload images manually
"""

import os
import webbrowser
import subprocess
import sys

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")

CMS_PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"
CMS_CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"
CHECKLIST_FILE = os.path.join(PROCESSED_IMAGES_DIR, "UPLOAD_CHECKLIST.txt")


def open_file(filepath):
    """Open a file with default application"""
    try:
        os.startfile(filepath)
        return True
    except Exception as e:
        print(f"Could not open {filepath}: {e}")
        return False


def open_folder(folderpath):
    """Open a folder in File Explorer"""
    try:
        os.startfile(folderpath)
        return True
    except Exception as e:
        print(f"Could not open {folderpath}: {e}")
        return False


def main():
    """Main function"""
    print("\n" + "="*80)
    print("BABY BILLION - QUICK START UPLOADER")
    print("="*80 + "\n")

    print("This will open everything you need to upload images:\n")

    print("[1] Opening UPLOAD_CHECKLIST.txt")
    print("    - Shows exactly which image goes where")
    print("    - Lists file paths for copy-paste")
    open_file(CHECKLIST_FILE)

    print("\n[2] Opening processed_images folder")
    print("    - Shows all ready-to-upload images")
    open_folder(PROCESSED_IMAGES_DIR)

    print("\n[3] Opening CMS in browser")
    print("    - Playlists: " + CMS_PLAYLISTS_URL)
    webbrowser.open(CMS_PLAYLISTS_URL)

    print("\n" + "="*80)
    print("MANUAL UPLOAD PROCESS")
    print("="*80 + "\n")

    print("For each entry in the checklist:\n")
    print("  1. Find the name in CMS (use search if available)")
    print("  2. Click 'Edit'")
    print("  3. Find the thumbnail upload fields")
    print("  4. Upload the image shown in checklist to BOTH fields")
    print("  5. Click 'Save'")
    print("  6. Go back and repeat\n")

    print("Tips:")
    print("  - Images are in: " + PROCESSED_IMAGES_DIR)
    print("  - All files are <200KB and properly sized")
    print("  - Copy full path from checklist for quick access")
    print("  - You can upload both fields at once")
    print("  - Save after each entry\n")

    print("Files ready to use:")
    playlists = len([f for f in os.listdir(os.path.join(PROCESSED_IMAGES_DIR, "playlists")) if f.endswith('.jpg')])
    characters = len([f for f in os.listdir(os.path.join(PROCESSED_IMAGES_DIR, "characters")) if f.endswith('.jpg')])
    categories = len([f for f in os.listdir(os.path.join(PROCESSED_IMAGES_DIR, "categories")) if f.endswith('.jpg')])

    print(f"  - Playlists: {playlists} images ready")
    print(f"  - Characters: {characters} images ready")
    print(f"  - Categories: {categories} images ready")
    print(f"  - Total: {playlists + characters + categories} images ready\n")

    print("="*80)
    print("Window/tabs should be opening now...")
    print("The checklist shows your upload guide")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
    input("Press ENTER to exit...")
