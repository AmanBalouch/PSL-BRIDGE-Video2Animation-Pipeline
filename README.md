# PSL Video to Animation

Download Pakistan Sign Language (PSL) dictionary videos and convert them into
3D `.glb` avatar animations — end to end, in one command.

- **Phase 1 — Download:** scrapes sign clips from [psl.org.pk](https://psl.org.pk)
- **Phase 2 — Animate:** drives [Animics](https://animics.gti.upf.edu/) to run
  MediaPipe pose extraction and export one `.glb` animation per clip

Both phases are **resume-safe**: an already-downloaded video is never fetched
again, and a video that already has a `.glb` is never re-animated.

## How it's organized

For every category you list, the pipeline creates two folders **next to these
scripts**:

```
PSL-Video-to-Animation/
├── config.py                     <- the only file you normally edit
├── run.py                        <- runs both phases
├── psl_download.py               <- phase 1 (can run alone)
├── animics_animate.py            <- phase 2 (can run alone)
├── common.py                     <- shared path/naming helpers
├── around-the-house_videos/      <- (generated) downloaded .mp4 clips
└── around-the-house_animations/  <- (generated) exported .glb animations
```

The category slug comes from the URL: `.../dictionary/10-around-the-house`
→ `around-the-house_videos` and `around-the-house_animations`.

## Setup

```bash
# from inside the project folder
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

You also need **Google Chrome** installed. Selenium 4 auto-downloads the
matching chromedriver — nothing else to install.

## Configure

Edit `config.py`. List one or more categories. `None` = whole category, a list =
only those specific words:

```python
CATEGORIES = {
    "https://psl.org.pk/dictionary/10-around-the-house": None,
    "https://psl.org.pk/dictionary/58-numbers": ["One", "two", "fifteen"],
}
```

## Run

```bash
python run.py                # download, then animate (full pipeline)

# or one phase at a time:
python psl_download.py       # download only
python animics_animate.py    # animate only (uses whatever is in *_videos/)
```

## Trim

Each clip is trimmed before pose extraction (default: first 50%). Change in
`config.py`:

```python
TRIM_START_RATIO = 0.0   # first 50%: 0.0 -> 0.5
TRIM_END_RATIO   = 0.5   # last 50%: 0.5 -> 1.0 | middle 50%: 0.25 -> 0.75
```

## Running on Mac vs EC2

- **Mac (local):** keep `HEADLESS_ANIMICS = False` in `config.py`. Animics uses
  WebGL + MediaPipe and is most reliable with a visible browser on a machine
  with a GPU.
- **EC2:** the **download** phase works fine on a headless server. The
  **Animics** phase needs a GPU-capable, WebGL-enabled Chrome; on a headless
  server run it under a virtual display (`xvfb-run python animics_animate.py`)
  and expect it to be slower. A simple split that works well: run
  `python psl_download.py` on EC2, copy the `*_videos/` folders, and run the
  Animics phase on a machine with a real GPU.

## Notes / limits

- Phase 2 drives Animics' internal JavaScript objects directly. This is more
  robust than clicking dialogs, but it can break if Animics renames those
  internals in a future update.
- A `trackCount: 0` warning means a `.glb` exported as a static (unanimated)
  avatar — worth re-checking that clip.
