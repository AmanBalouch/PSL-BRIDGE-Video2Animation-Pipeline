"""
psl_download.py -- Phase 1: download PSL Dictionary videos.

For every category in config.CATEGORIES it downloads the requested words (or the
whole category) into <category>_videos/, keeping the website's exact word as the
filename. It is resume-safe: a word whose .mp4 already exists is skipped, so an
already-downloaded video is never fetched from the PSL directory again.

Run this phase on its own:
    python psl_download.py

Videos land in <category>_videos/<word>.mp4 (filename EXACTLY as on the website:
spaces, brackets, capitalization all preserved; only '/' and ':' are replaced
because a filesystem can't contain them).
"""
import os
import re
import shutil
import time
import urllib.request

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config
from common import category_slug, videos_dir_for

BASE_URL = "https://psl.org.pk"


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def _hide_stale_chromedriver_from_path():
    """If an outdated chromedriver is on PATH (common after a Chrome update),
    remove its folder from PATH so Selenium Manager fetches the matching one."""
    found = shutil.which("chromedriver")
    if not found:
        return
    stale_dir = os.path.dirname(found)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p != stale_dir]
    os.environ["PATH"] = os.pathsep.join(parts)


def make_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    try:
        driver = webdriver.Chrome(options=options)
    except SessionNotCreatedException:
        print("[INFO] chromedriver in PATH is outdated; letting Selenium Manager "
              "fetch the matching one...")
        _hide_stale_chromedriver_from_path()
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


# --------------------------------------------------------------------------- #
# Scraping
# --------------------------------------------------------------------------- #
def scroll_to_bottom(driver, pause=0.5, max_loops=30):
    """Category cards lazy-load on scroll; keep scrolling until height settles."""
    last_height = -1
    for _ in range(max_loops):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)
        height = driver.execute_script("return document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height


def collect_word_links(driver, category_url):
    """Return {word_page_url: word} for every card on the category page."""
    driver.get(category_url)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
    scroll_to_bottom(driver)

    category_path = "/" + category_url.split("/", 3)[-1].rstrip("/")  # /dictionary/58-numbers
    cards = driver.find_elements(By.CSS_SELECTOR, f'a[href^="{category_path}/"]')

    words = {}
    for card in cards:
        href = card.get_attribute("href")
        if not href:
            continue
        try:
            word = card.find_element(By.TAG_NAME, "h3").text.strip()
        except Exception:
            word = card.text.strip()
        if href and word:
            words[href] = word
    return words


def extract_video_url(driver, word_url):
    """Open a word page and return the .mp4 URL of its sign video."""
    driver.get(word_url)
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script(
                "return document.querySelector('video source')?.src "
                "|| document.querySelector('video')?.src || ''"
            )
        )
    except Exception:
        pass
    time.sleep(0.5)

    src = driver.execute_script(
        "return document.querySelector('video source')?.src "
        "|| document.querySelector('video')?.src || ''"
    )
    if src:
        return src

    match = re.search(r'https://[^"\']+?\.mp4', driver.page_source)
    return match.group(0) if match else None


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def safe_filename(text):
    """Keep the website name as-is; only drop characters a path can't hold."""
    text = text.strip().replace("/", "-").replace(":", "-")
    return text or "unknown"


def download_video(url, dest_path):
    """Stream a video to disk via a temp file so a partial download never leaves
    behind a corrupt final file (which would then look 'already downloaded')."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    tmp_path = dest_path + ".tmp"
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    os.replace(tmp_path, dest_path)


# --------------------------------------------------------------------------- #
# One category
# --------------------------------------------------------------------------- #
def download_category(driver, category_url, out_dir, wanted_words=None):
    """Download one category's videos into out_dir.
    wanted_words=None -> whole category; otherwise only those words."""
    os.makedirs(out_dir, exist_ok=True)
    print(f"\nOpening category page: {category_url}")
    word_links = collect_word_links(driver, category_url)   # {url: word}
    print(f"Found {len(word_links)} words on the page.")

    if wanted_words is not None:
        wanted_lower = {w.strip().lower(): w for w in wanted_words}
        selected = {url: word for url, word in word_links.items()
                    if word.strip().lower() in wanted_lower}
        found_lower = {word.strip().lower() for word in selected.values()}
        missing = [orig for low, orig in wanted_lower.items() if low not in found_lower]
        if missing:
            print(f"  [WARN] Not found in this category: {', '.join(missing)}")
        word_links = selected
        print(f"Vocab match: {len(word_links)} word(s) to download.")

    total = len(word_links)
    for i, (word_url, word) in enumerate(word_links.items(), 1):
        dest = os.path.join(out_dir, safe_filename(word) + ".mp4")
        # RESUME: an already-downloaded video is never re-fetched.
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"[{i}/{total}] {word} - already downloaded")
            continue

        print(f"[{i}/{total}] {word} - fetching video URL...", end=" ")
        video_url = extract_video_url(driver, word_url)
        if not video_url:
            print("NOT FOUND")
            continue
        try:
            download_video(video_url, dest)
            print("OK")
        except Exception as e:
            print(f"DOWNLOAD FAILED: {e}")


def download_all(categories=None):
    """Download every category in the config (or a passed-in dict)."""
    categories = categories if categories is not None else config.CATEGORIES
    driver = make_driver(headless=not config.SHOW_BROWSER_DOWNLOAD)
    try:
        for category_url, words in categories.items():
            out_dir = videos_dir_for(category_url)
            print(f"\n===== DOWNLOAD: {category_slug(category_url)} =====")
            download_category(driver, category_url, out_dir, wanted_words=words)
    finally:
        driver.quit()


if __name__ == "__main__":
    download_all()
    print("\nDownload phase done.")
