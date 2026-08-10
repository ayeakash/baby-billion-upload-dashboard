"""
Semi-Automatic CMS Image Uploader
Opens browser and guides you through uploads step-by-step
"""

import os
import json
import webbrowser
import time
from pathlib import Path

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")
CHECKLIST_FILE = os.path.join(PROCESSED_IMAGES_DIR, "UPLOAD_CHECKLIST.txt")

CMS_PLAYLISTS_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists"
CMS_CATEGORIES_URL = "https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/categories"


def read_checklist():
    """Read and parse the upload checklist"""
    if not os.path.exists(CHECKLIST_FILE):
        print(f"[ERROR] Checklist not found: {CHECKLIST_FILE}")
        return None

    playlists = []
    categories = []
    characters = []
    current_section = None

    with open(CHECKLIST_FILE, 'r') as f:
        for line in f:
            line = line.strip()

            if "PLAYLISTS TO UPLOAD" in line:
                current_section = "playlists"
            elif "CHARACTERS TO UPLOAD" in line:
                current_section = "characters"
            elif "CATEGORIES TO UPLOAD" in line:
                current_section = "categories"
            elif line.startswith("Playlist:"):
                name = line.replace("Playlist:", "").strip()
                playlists.append(name)
            elif line.startswith("Character:"):
                name = line.replace("Character:", "").strip()
                characters.append(name)
            elif line.startswith("Category:"):
                name = line.replace("Category:", "").strip()
                categories.append(name)

    return {
        'playlists': playlists,
        'characters': characters,
        'categories': categories
    }


def get_image_file(category_type, name):
    """Get image file path for a given name"""
    image_dir = os.path.join(PROCESSED_IMAGES_DIR, category_type)
    image_file = os.path.join(image_dir, f"{name.lower().replace(' ', '_')}.jpg")

    if os.path.exists(image_file):
        return image_file

    # Try without replacing spaces
    for fname in os.listdir(image_dir):
        if fname.lower().replace('.jpg', '') == name.lower():
            return os.path.join(image_dir, fname)

    return None


def print_header(title):
    """Print a formatted header"""
    print("\n" + "="*80)
    print(title.center(80))
    print("="*80 + "\n")


def print_step(step_num, instruction):
    """Print a numbered step"""
    print(f"[Step {step_num}] {instruction}")


def upload_playlists_guided():
    """Guide user through uploading playlists"""
    print_header("UPLOADING PLAYLISTS")

    webbrowser.open(CMS_PLAYLISTS_URL)
    print(f"Opening: {CMS_PLAYLISTS_URL}\n")
    time.sleep(3)

    playlists = [
        "Alphabets", "Animals", "Around Us", "Curious Kids", "English",
        "Geography", "Hindi Basics", "Manners", "Math", "Nature",
        "Numbers", "Our World", "Rhymes", "Science", "Stories"
    ]

    print(f"Total playlists to upload: {len(playlists)}\n")

    for idx, playlist_name in enumerate(playlists, 1):
        print(f"\n{'='*80}")
        print(f"Playlist {idx}/{len(playlists)}: {playlist_name}")
        print(f"{'='*80}")

        # Get image file
        image_name = playlist_name.lower().replace(' ', '_')
        image_file = os.path.join(PROCESSED_IMAGES_DIR, "playlists", f"{image_name}.jpg")

        if not os.path.exists(image_file):
            print(f"[WARN] Image not found: {image_file}")
            print(f"Available files: {os.listdir(os.path.join(PROCESSED_IMAGES_DIR, 'playlists'))}\n")
            continue

        file_size_kb = os.path.getsize(image_file) / 1024

        print_step(1, f"Find '{playlist_name}' in the playlist list")
        print_step(2, f"Click 'Edit' button")
        print_step(3, f"Upload this file to BOTH thumbnail fields:")
        print(f"\n  File: {os.path.basename(image_file)}")
        print(f"  Size: {file_size_kb:.1f}KB")
        print(f"  Full path: {image_file}\n")

        print_step(4, "Click 'Save'")
        print_step(5, "Wait for confirmation\n")

        response = input("Press ENTER when upload is complete (or 'skip' to skip): ").strip().lower()

        if response == "skip":
            print(f"[SKIP] Skipped {playlist_name}")
        else:
            print(f"[OK] Recorded upload for {playlist_name}")


def upload_categories_guided():
    """Guide user through uploading categories"""
    print_header("UPLOADING CATEGORIES")

    webbrowser.open(CMS_CATEGORIES_URL)
    print(f"Opening: {CMS_CATEGORIES_URL}\n")
    time.sleep(3)

    categories = [
        "ABC", "About India", "Action Words", "Aladdin", "Animals",
        "Birds", "Body Parts", "Clothes", "Colors", "Community Helpers",
        "Countries", "Emotions", "English", "English Speaking", "Farm Animals",
        "Festivals", "Food Items", "Fractions", "Fruits", "Good Habits",
        "Greater and Lesser", "Hanuman", "Hindi Basics", "Home Items", "Knowledge",
        "Mishka and Momo", "MS Isha", "MS Nidhi", "MS Pranika", "My Body",
        "My Family", "Nature", "Opposites", "Panchatantra", "Places to Go",
        "Plants", "Prepositions", "Professions", "Safety", "Science",
        "Seasons", "Shivji", "Sight Words", "Simple Sentences", "Sindbad",
        "Space", "Sports", "Technology", "Tenali", "Time",
        "Toys", "Varnmala", "Vegetables", "Vehicles", "Vyanjan",
        "Wild Animals", "Words", "Krishna"
    ]

    print(f"Total categories to upload: {len(categories)}\n")

    uploaded_count = 0
    for idx, category_name in enumerate(categories, 1):
        print(f"\n{'='*80}")
        print(f"Category {idx}/{len(categories)}: {category_name}")
        print(f"{'='*80}")

        # Get image file
        image_name = category_name.lower().replace(' ', '_')
        image_file = os.path.join(PROCESSED_IMAGES_DIR, "categories", f"{image_name}.jpg")

        if not os.path.exists(image_file):
            print(f"[WARN] Image not found: {image_file}")
            continue

        file_size_kb = os.path.getsize(image_file) / 1024

        print_step(1, f"Find '{category_name}' in the category list")
        print_step(2, f"Click 'Edit' button")
        print_step(3, f"Upload this file to BOTH thumbnail fields:")
        print(f"\n  File: {os.path.basename(image_file)}")
        print(f"  Size: {file_size_kb:.1f}KB")
        print(f"  Full path: {image_file}\n")

        print_step(4, "Click 'Save'")
        print_step(5, "Wait for confirmation\n")

        response = input("Press ENTER when upload is complete (or 'skip' to skip, or 'quit' to stop): ").strip().lower()

        if response == "skip":
            print(f"[SKIP] Skipped {category_name}")
        elif response == "quit":
            print(f"\nStopped at {category_name}")
            break
        else:
            print(f"[OK] Recorded upload for {category_name}")
            uploaded_count += 1

    return uploaded_count


def main():
    """Main function"""
    print_header("BABY BILLION CMS SEMI-AUTO UPLOADER")

    print("This script will guide you through uploading images to the CMS.")
    print("You will control the actual uploads - this script just shows you what to do.\n")

    print("What you need:")
    print("  - CMS login credentials")
    print("  - Access to the CMS at: " + CMS_PLAYLISTS_URL)
    print("  - About 2-3 hours (for manual uploads)")
    print("  - Processed images are ready in: " + PROCESSED_IMAGES_DIR + "\n")

    response = input("Continue? (yes/no): ").strip().lower()
    if response != "yes":
        print("Cancelled.")
        return

    try:
        # Upload playlists
        upload_playlists_guided()

        # Ask before categories
        response = input("\n\nContinue to categories? (yes/no): ").strip().lower()
        if response == "yes":
            uploaded = upload_categories_guided()
        else:
            uploaded = 0

        # Summary
        print_header("UPLOAD COMPLETE")
        print(f"Categories uploaded: {uploaded}")
        print(f"\nAll images are ready in: {PROCESSED_IMAGES_DIR}")
        print("Check PROCESSING_REPORT.txt for image details")

    except KeyboardInterrupt:
        print("\n\n[WARN] Upload cancelled by user")
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")


if __name__ == "__main__":
    main()
