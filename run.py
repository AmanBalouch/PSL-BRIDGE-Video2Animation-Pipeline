"""
run.py -- the whole pipeline in one command.

    python run.py

Phase 1: download every category's PSL videos into <category>_videos/
Phase 2: convert each downloaded video into a .glb animation in <category>_animations/

Both phases are resume-safe:
  - a video that already exists is NOT re-downloaded from the PSL directory
  - a video whose .glb already exists is NOT re-animated on Animics

Edit config.py to choose your categories/words. To run a single phase instead:
    python psl_download.py     # downloads only
    python animics_animate.py  # animates only
"""
import config
import psl_download
import animics_animate
from common import category_slug, videos_dir_for, animations_dir_for


def main():
    categories = config.CATEGORIES
    if not categories:
        print("config.CATEGORIES is empty - add at least one category URL in config.py")
        return

    print("Categories in this run:")
    for url, words in categories.items():
        what = "whole category" if words is None else f"{len(words)} word(s): {', '.join(words)}"
        print(f"  - {category_slug(url)}  ({what})")
        print(f"      videos     -> {videos_dir_for(url)}")
        print(f"      animations -> {animations_dir_for(url)}")

    print("\n########## PHASE 1: DOWNLOAD PSL VIDEOS ##########")
    psl_download.download_all(categories)

    print("\n########## PHASE 2: CONVERT TO ANIMATIONS (Animics) ##########")
    animics_animate.animate_all(categories)

    print("\nAll done. Videos in *_videos/, animations in *_animations/.")


if __name__ == "__main__":
    main()
