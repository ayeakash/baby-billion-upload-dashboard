#!/usr/bin/env python3
"""
Scrape CMS playlists and categories using Selenium headless browser.
"""

import json
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import sys

sys.path.insert(0, "pipeline")
from credentials import BB_USERNAME, BB_PASSWORD

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

CMS_BASE = "https://cms-v1.d148rwrq639wa8.amplifyapp.com"
PLAYLISTS_CACHE_FILE = ".playlists_cache.json"

def scrape_playlists():
    """Scrape playlists from CMS using headless browser."""

    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = None
    playlists = []

    try:
        log.info("Starting Chrome headless browser...")
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)

        # First, try to navigate to login page directly
        log.info("Navigating to login page...")
        login_url = f"{CMS_BASE}/login"
        driver.get(login_url)
        time.sleep(2)

        # Wait for and fill login form
        try:
            log.info("Waiting for login form...")
            email_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "email"))
            )
            log.info("Login form found, entering credentials...")

            # Clear and enter email
            email_field.clear()
            email_field.send_keys(BB_USERNAME)
            time.sleep(0.5)

            # Enter password
            password_field = driver.find_element(By.NAME, "password")
            password_field.clear()
            password_field.send_keys(BB_PASSWORD)
            time.sleep(0.5)

            # Click login button
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Login') or @type='submit']"))
            )
            log.info("Clicking login button...")
            submit_button.click()

            # Wait for redirect and page load
            log.info("Waiting for login to complete...")
            time.sleep(5)

            # Navigate to playlists page
            log.info("Navigating to playlists page...")
            playlists_url = f"{CMS_BASE}/dashboard/cms/playlists"
            driver.get(playlists_url)
            time.sleep(3)

        except Exception as e:
            log.error(f"Login failed: {e}")
            log.info("Attempting to navigate directly to playlists page...")
            playlists_url = f"{CMS_BASE}/dashboard/cms/playlists"
            driver.get(playlists_url)
            time.sleep(3)

        # Wait for playlists content to load
        log.info("Waiting for playlists to load...")

        # More aggressive waiting for content
        for attempt in range(5):
            try:
                # Look for any meaningful content
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                if len(body_text) > 100 and 'playlist' in body_text.lower():
                    log.info(f"Found meaningful content on attempt {attempt + 1}")
                    break
                time.sleep(2)
            except:
                time.sleep(2)

        # Take a screenshot for debugging
        try:
            driver.save_screenshot("cms_playlists_page.png")
            log.info("Screenshot saved as cms_playlists_page.png")
        except Exception as e:
            log.debug(f"Failed to save screenshot: {e}")

        time.sleep(2)

        # Extract playlists from page
        log.info("Extracting playlists from page...")
        playlists = _extract_playlists_from_page(driver)

        log.info(f"Found {len(playlists)} playlists")

        # For each playlist, try to fetch its categories by clicking edit
        for i, playlist in enumerate(playlists):
            log.info(f"Processing playlist {i+1}/{len(playlists)}: {playlist['title']}")
            try:
                categories = _fetch_playlist_categories(driver, playlist, playlists_url)
                playlist['categories'] = categories
                log.info(f"  Found {len(categories)} categories")
            except Exception as e:
                log.warning(f"Failed to fetch categories for {playlist['title']}: {e}")
                playlist['categories'] = []

        # Save to cache file
        log.info(f"Saving {len(playlists)} playlists to cache...")
        with open(PLAYLISTS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(playlists, f, indent=2, ensure_ascii=False)

        log.info(f"✓ Successfully saved {len(playlists)} playlists to {PLAYLISTS_CACHE_FILE}")
        return playlists

    except Exception as e:
        log.error(f"Error scraping playlists: {e}", exc_info=True)
        return []

    finally:
        if driver:
            log.info("Closing browser...")
            driver.quit()

def _extract_playlists_from_page(driver):
    """Extract playlists from the loaded page."""
    playlists = []

    try:
        # Get page source for debugging
        page_source = driver.page_source
        log.info(f"Page source length: {len(page_source)} bytes")

        # Look for any data that might contain playlists
        if 'playlist' in page_source.lower():
            log.info("Found 'playlist' text in page source")

        # Try to find playlists in a table
        rows = driver.find_elements(By.XPATH, "//tr")
        log.info(f"Found {len(rows)} table rows")

        if len(rows) > 1:
            # Skip header row (if present)
            for row in rows[1:]:
                try:
                    cells = row.find_elements(By.XPATH, ".//td")
                    if len(cells) > 0:
                        # First cell usually contains title/name
                        title_elem = cells[0].find_element(By.XPATH, ".//a | .//span | .")
                        title = title_elem.text.strip()

                        if title and len(title) > 0:
                            # Look for edit link
                            edit_link = None
                            try:
                                edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit') or contains(@href, 'edit')]")
                                edit_url = edit_link.get_attribute('href')
                            except:
                                edit_url = None

                            playlist = {
                                "id": title.lower().replace(" ", "-"),
                                "title": title,
                                "edit_url": edit_url,
                                "categories": []
                            }

                            # Avoid duplicates
                            if title not in [p['title'] for p in playlists]:
                                playlists.append(playlist)
                except Exception as e:
                    log.debug(f"Error processing row: {e}")
                    continue

        # If no table found, try other selectors
        if not playlists:
            log.info("No table rows found, trying div-based layout...")
            playlist_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'playlist') or contains(@class, 'item')]")
            log.info(f"Found {len(playlist_items)} playlist items")

            for item in playlist_items[:20]:  # Limit to first 20 items
                try:
                    title_elem = item.find_element(By.XPATH, ".//h3 | .//h4 | .//span[@class*='title'] | .//a")
                    title = title_elem.text.strip()

                    if title and len(title) > 3:
                        edit_link = None
                        try:
                            edit_link = item.find_element(By.XPATH, ".//a[contains(@href, 'edit')]")
                            edit_url = edit_link.get_attribute('href')
                        except:
                            edit_url = None

                        playlist = {
                            "id": title.lower().replace(" ", "-"),
                            "title": title,
                            "edit_url": edit_url,
                            "categories": []
                        }

                        if title not in [p['title'] for p in playlists]:
                            playlists.append(playlist)
                except Exception as e:
                    log.debug(f"Error processing item: {e}")
                    continue

    except Exception as e:
        log.error(f"Error extracting playlists: {e}")

    return playlists

def _fetch_playlist_categories(driver, playlist, base_url):
    """Fetch categories for a playlist by navigating to its edit page."""
    categories = []

    try:
        edit_url = playlist.get('edit_url')
        if not edit_url:
            log.debug(f"No edit URL for {playlist['title']}")
            return categories

        # Construct full URL if relative
        if edit_url.startswith('/'):
            edit_url = CMS_BASE + edit_url
        elif not edit_url.startswith('http'):
            edit_url = CMS_BASE + '/' + edit_url

        log.info(f"Fetching categories from: {edit_url}")

        # Store current window handle
        current_window = driver.current_window_handle

        # Open edit page in same tab
        driver.get(edit_url)
        time.sleep(2)

        # Extract categories from edit page
        categories = _extract_categories_from_edit_page(driver)

        # Go back to playlists list
        driver.get(base_url)
        time.sleep(1)

    except Exception as e:
        log.warning(f"Failed to fetch categories: {e}")

    return categories

def _extract_categories_from_edit_page(driver):
    """Extract categories from playlist edit page."""
    categories = []

    try:
        # Scroll down to find category selection
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # Look for checkboxes with category names
        checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
        log.info(f"Found {len(checkboxes)} checkboxes")

        for checkbox in checkboxes:
            try:
                # Get the label text associated with this checkbox
                label = checkbox.find_element(By.XPATH, "./../..//label | .//..//label | ./following::label[1]")
                cat_text = label.text.strip()

                if cat_text and len(cat_text) < 100:
                    categories.append({
                        "id": checkbox.get_attribute('value') or cat_text.lower().replace(" ", "-"),
                        "title": cat_text
                    })
            except:
                try:
                    # Try getting text from parent element
                    parent = checkbox.find_element(By.XPATH, "./..")
                    cat_text = parent.text.strip()
                    if cat_text:
                        categories.append({
                            "id": cat_text.lower().replace(" ", "-"),
                            "title": cat_text
                        })
                except:
                    pass

        # Look for select/option elements
        select_elements = driver.find_elements(By.XPATH, "//select")
        for select in select_elements:
            try:
                options = select.find_elements(By.XPATH, ".//option")
                for option in options:
                    cat_text = option.text.strip()
                    if cat_text and cat_text.lower() not in ['select', 'choose', 'none', '']:
                        cat_id = option.get_attribute('value') or cat_text.lower().replace(" ", "-")
                        if cat_id not in [c['id'] for c in categories]:
                            categories.append({
                                "id": cat_id,
                                "title": cat_text
                            })
            except:
                pass

        # Look for category tags/chips
        category_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'category') or contains(@class, 'tag') or contains(@class, 'chip')]")
        for elem in category_elements[:30]:  # Limit to first 30
            try:
                cat_text = elem.text.strip()
                if cat_text and len(cat_text) < 100 and cat_text not in [c['title'] for c in categories]:
                    categories.append({
                        "id": cat_text.lower().replace(" ", "-"),
                        "title": cat_text
                    })
            except:
                pass

        # Remove duplicates
        seen = set()
        unique = []
        for cat in categories:
            key = cat['title'].lower()
            if key not in seen:
                seen.add(key)
                unique.append(cat)

        return unique

    except Exception as e:
        log.warning(f"Error extracting categories: {e}")
        return []

if __name__ == "__main__":
    log.info("Starting CMS Playlists Scraper...")
    playlists = scrape_playlists()

    if playlists:
        print(f"\nSuccessfully scraped {len(playlists)} playlists!")
        print("\nPlaylist Summary:")
        for p in playlists:
            print(f"  - {p['title']}: {len(p['categories'])} categories")
    else:
        print("\nNo playlists found. Check the screenshot and logs for details.")
        log.info("Screenshot should be at cms_playlists_page.png")
        sys.exit(1)
