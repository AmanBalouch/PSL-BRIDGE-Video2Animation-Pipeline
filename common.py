"""
common.py -- shared helpers: where the per-category folders live and how they
are named. Everything is created NEXT TO these script files (BASE_DIR), so the
project is fully self-contained and works the same on your Mac and on EC2,
regardless of the current working directory.
"""
import os
import re

# The folder that contains these scripts. All _videos / _animations folders are
# created here, so "python run.py" behaves identically no matter where you cd.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def category_slug(category_url):
    """https://psl.org.pk/dictionary/10-around-the-house -> around-the-house

    Takes the last URL segment and strips the leading "<number>-" id so the
    folder name is human readable.
    """
    last = category_url.rstrip("/").split("/")[-1]     # 10-around-the-house
    slug = re.sub(r"^\d+-", "", last)                  # around-the-house
    return slug or last


def videos_dir_for(category_url):
    """Absolute path to this category's downloaded-videos folder."""
    return os.path.join(BASE_DIR, category_slug(category_url) + "_videos")


def animations_dir_for(category_url):
    """Absolute path to this category's exported-animations folder."""
    return os.path.join(BASE_DIR, category_slug(category_url) + "_animations")
