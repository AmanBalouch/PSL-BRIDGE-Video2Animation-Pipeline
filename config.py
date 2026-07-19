"""
config.py -- The ONLY file you normally need to edit.

Add one or more PSL dictionary category URLs below. For each category you can
either download the WHOLE category, or just a few specific words.

For every category the pipeline creates two folders NEXT TO these scripts:
    <category>_videos/       <- PSL .mp4 clips are downloaded here
    <category>_animations/   <- Animics .glb animations are exported here

e.g. for "https://psl.org.pk/dictionary/10-around-the-house" you get
    around-the-house_videos/  and  around-the-house_animations/
"""

# ---------------------------------------------------------------------------
# CATEGORIES: {category_url: words}
#   words = None          -> download the WHOLE category
#   words = ["a", "b"]    -> download only those specific words (case-insensitive)
#
# You can list as many categories as you want.
# ---------------------------------------------------------------------------
CATEGORIES = {
    "https://psl.org.pk/dictionary/10-around-the-house": ["Grill"],
}

# ---------------------------------------------------------------------------
# DOWNLOAD (PSL) settings
# ---------------------------------------------------------------------------
SHOW_BROWSER_DOWNLOAD = False   # True -> watch the download browser (debugging)

# ---------------------------------------------------------------------------
# ANIMATION (Animics) settings
# ---------------------------------------------------------------------------
# Each clip is trimmed to [START, END] of its duration before pose extraction.
#   first 50%  -> START=0.0, END=0.5   (default)
#   last  50%  -> START=0.5, END=1.0
#   middle 50% -> START=0.25, END=0.75
TRIM_START_RATIO = 0.0
TRIM_END_RATIO = 0.5

# Keep False on a machine with a real GPU (Animics uses WebGL + MediaPipe and
# is far more reliable with a visible browser). See README for EC2/headless.
HEADLESS_ANIMICS = False

# Restart Chrome every CHUNK_SIZE videos to bound WebGL/MediaPipe memory growth.
CHUNK_SIZE = 8

# How many Chrome instances to run at the SAME TIME per category (CPU/GPU heavy).
NUM_WORKERS = 1
