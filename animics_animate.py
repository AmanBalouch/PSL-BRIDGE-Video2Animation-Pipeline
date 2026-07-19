"""
animics_animate.py -- Phase 2: turn downloaded PSL videos into .glb animations.

For every category it reads the .mp4 files from <category>_videos/, drives
Animics (https://animics.gti.upf.edu/) one clip at a time, and exports one .glb
mocap animation per clip into <category>_animations/. It is resume-safe: a video
whose .glb already exists in the animations folder is skipped, so a clip that has
already been animated is never processed again.

Run this phase on its own (after downloading):
    python animics_animate.py

HOW IT WORKS (and why it should be reliable)
--------------------------------------------
Animics is open source (github.com/upf-gti/animics). Instead of guessing button
clicks, this script drives Animics' own internal objects/functions directly via
JavaScript, exactly the way Animics calls them itself:
  - It trims each clip with videoEditor.timebar.setStartTime/setEndTime.
  - It calls editor.setGlobalAnimation(name) BEFORE bindAnimationToCharacter(name)
    (Animics' Editor.js does the same; skipping setGlobalAnimation is what makes a
    GLB export as a static, unanimated avatar with trackCount 0).
  - It exports with editor.export([name], 'GLB', true, name) -> one <name>.glb.
This is robust against dialog wording changes, but it does depend on Animics'
internal object names staying the same across updates.
"""
import os
import glob
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException, SessionNotCreatedException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config
from common import category_slug, videos_dir_for, animations_dir_for

ANIMICS_URL = "https://animics.gti.upf.edu/"

# Timeouts. The FIRST video of every browser session is slower because Animics
# has to download/initialize MediaPipe's pose models before it can show trim.
FIRST_VIDEO_LOAD_TIMEOUT_SEC = 300
VIDEO_LOAD_TIMEOUT_SEC = 240
PER_VIDEO_TIMEOUT_SEC = 480     # max wait for pose extraction on one video
HEARTBEAT_SEC = 15              # print a "still working" line this often

PAGE_LOAD_RETRIES = 3
PAGE_LOAD_RETRY_DELAY_SEC = 5

_print_lock = threading.Lock()


def log(worker_id, msg):
    prefix = f"[W{worker_id}] " if worker_id is not None else ""
    with _print_lock:
        print(f"{prefix}{msg}")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def safe_click(driver, element, worker_id=None, retries=6, delay=0.5):
    """Click, tolerating Animics' loading overlay intercepting the click; fall
    back to a JS click which bypasses the interception check entirely."""
    for _ in range(retries):
        try:
            element.click()
            return
        except ElementClickInterceptedException:
            time.sleep(delay)
    log(worker_id, "  (click intercepted repeatedly, forcing a JS click)")
    driver.execute_script("arguments[0].click();", element)


def build_driver(download_folder, worker_id=None, window_index=0):
    options = Options()
    if config.HEADLESS_ANIMICS:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1280,900")
        # Software WebGL so Animics' Three.js/MediaPipe render WITHOUT a GPU
        # (needed on a headless EC2 box). Newer Chrome blocks SwiftShader WebGL
        # in headless mode unless this flag is set.
        options.add_argument("--use-gl=angle")
        options.add_argument("--use-angle=swiftshader")
        options.add_argument("--enable-unsafe-swiftshader")
    else:
        # Offset each worker's window so they don't stack exactly on top.
        cols, w, h = 3, 700, 500
        x = (window_index % cols) * (w + 20)
        y = (window_index // cols) * (h + 40)
        options.add_argument(f"--window-position={x},{y}")
        options.add_argument(f"--window-size={w},{h}")
    # Required on a headless Linux server (root/limited namespaces); harmless
    # on a desktop. /dev/shm is tiny on many EC2 AMIs, so don't rely on it.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_folder,
            "download.prompt_for_download": False,
            "profile.default_content_setting_values.automatic_downloads": 1,
        },
    )
    try:
        driver = webdriver.Chrome(options=options)
    except SessionNotCreatedException:
        # Outdated chromedriver on PATH -> let Selenium Manager fetch a match.
        import shutil
        found = shutil.which("chromedriver")
        if found:
            stale_dir = os.path.dirname(found)
            os.environ["PATH"] = os.pathsep.join(
                p for p in os.environ.get("PATH", "").split(os.pathsep) if p != stale_dir
            )
        driver = webdriver.Chrome(options=options)
    driver.set_script_timeout(30)
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": download_folder},
    )
    return driver


def get_with_retries(driver, url, worker_id=None, retries=PAGE_LOAD_RETRIES,
                     delay=PAGE_LOAD_RETRY_DELAY_SEC):
    """Load a URL, retrying on transient DNS/connection errors."""
    for attempt in range(1, retries + 1):
        driver.get(url)
        if not driver.find_elements(By.ID, "main-frame-error"):
            return True
        last_error = driver.execute_script(
            "return (document.getElementById('main-frame-error') || {}).innerText || '';"
        )
        log(worker_id, f"  Page failed to load (attempt {attempt}/{retries}): "
                       f"{last_error.splitlines()[0] if last_error else 'unknown error'}")
        time.sleep(delay)
    log(worker_id, "Could not load the page after several retries - is the "
                   "internet/DNS working for this browser right now?")
    return False


def wait_until_js(driver, script, timeout=60, poll=1.0, args=(), heartbeat=None,
                  worker_id=None):
    """Poll a JS script (must `return` truthy/falsy) until it's true."""
    end = time.time() + timeout
    last_heartbeat = time.time()
    while time.time() < end:
        try:
            if driver.execute_script(script, *args):
                return True
        except Exception:
            pass
        if heartbeat and (time.time() - last_heartbeat) >= heartbeat:
            log(worker_id, f"    ...still working ({int(end - time.time())}s left before timeout)")
            last_heartbeat = time.time()
        time.sleep(poll)
    return False


# ---- JS snippets (dynamic values passed via arguments[]) ------------------- #
CREATE_INPUT_JS = """
const input = document.createElement('input');
input.type = 'file';
input.multiple = true;
input.id = 'seleniumVideoInput';
input.style.position = 'fixed';
input.style.top = '0px';
input.style.left = '0px';
input.style.opacity = '0.01';
input.style.zIndex = '999999';
document.body.appendChild(input);
"""

EDITOR_READY_JS = """
return !!(window.global && window.global.app && window.global.app.editor &&
          window.global.app.videoProcessor && window.global.app.editor.currentCharacter);
"""

START_PROCESSING_JS = """
const index = arguments[0];
window.__animationReady = false;
window.__lastAnimation = null;
const app = window.global.app;
const file = document.getElementById('seleniumVideoInput').files[index];
app.processVideos([file]).then(function(anim) {
    window.__lastAnimation = anim ? anim[0] : null;
    window.__animationReady = true;
});
return file ? file.name : null;
"""

VIDEO_LOADED_JS = """
const vp = window.global.app.videoProcessor;
return !!(vp && vp.videoEditor && vp.videoEditor.video &&
          vp.videoEditor.video.duration && !isNaN(vp.videoEditor.video.duration));
"""

SET_TRIM_JS = """
const startRatio = arguments[0];
const endRatio = arguments[1];
const ve = window.global.app.videoProcessor.videoEditor;
const d = ve.video.duration;
ve.timebar.setStartTime(d * startRatio);
ve.timebar.setEndTime(d * endRatio);
return {duration: d, start: d * startRatio, end: d * endRatio};
"""

ANIMATION_READY_JS = "return window.__animationReady === true;"

# Async: awaits bind (retargeting/IK), reports how many tracks actually bound
# BEFORE exporting - the diagnostic that tells us the GLB really has motion data.
FINALIZE_EXPORT_JS = """
const callback = arguments[arguments.length - 1];
(async () => {
    try {
        const editor = window.global.app.editor;
        const anim = window.__lastAnimation;
        if (!anim) { callback({ok: false, reason: 'no animation data'}); return; }

        const name = editor.buildAnimation(anim, false);
        editor.setGlobalAnimation(name);
        await editor.bindAnimationToCharacter(name);
        await new Promise(r => setTimeout(r, 400));

        const boundAnim = editor.boundAnimations[editor.currentCharacter.name]
            ? editor.boundAnimations[editor.currentCharacter.name][name]
            : null;

        let trackCount = 0;
        if (boundAnim) {
            trackCount = boundAnim.mixerAnimation
                ? boundAnim.mixerAnimation.tracks.length
                : editor.generateExportAnimationData(boundAnim).tracks.length;
        }

        editor.export([name], 'GLB', true, name);
        callback({ok: true, name: name, bound: !!boundAnim, trackCount: trackCount});
    } catch (e) {
        callback({ok: false, reason: String(e && e.stack || e)});
    }
})();
"""


# --------------------------------------------------------------------------- #
# Processing
# --------------------------------------------------------------------------- #
def start_session(driver, wait, chunk_videos, worker_id=None):
    """Load Animics, start a Keyframe project, hand it this chunk's videos."""
    if not get_with_retries(driver, ANIMICS_URL, worker_id=worker_id):
        return False

    keyframe_btn = wait.until(EC.element_to_be_clickable((By.ID, "keyframe-project")))
    safe_click(driver, keyframe_btn, worker_id=worker_id)

    log(worker_id, "Waiting for the Keyframe editor to initialize...")
    if not wait_until_js(driver, EDITOR_READY_JS, timeout=60, worker_id=worker_id):
        log(worker_id, "Editor did not initialize in time.")
        return False

    driver.execute_script(CREATE_INPUT_JS)
    file_input = wait.until(EC.presence_of_element_located((By.ID, "seleniumVideoInput")))
    file_input.send_keys("\n".join(chunk_videos))

    num_files = driver.execute_script(
        "return document.getElementById('seleniumVideoInput').files.length;"
    )
    log(worker_id, f"{num_files} video(s) selected in the browser for this session.")
    return num_files == len(chunk_videos)


def process_video(driver, wait, index, is_first_in_session, worker_id=None):
    """Process one already-selected video by index. Returns a result dict."""
    video_name = driver.execute_script(START_PROCESSING_JS, index)
    log(worker_id, f"> {video_name}")

    load_timeout = FIRST_VIDEO_LOAD_TIMEOUT_SEC if is_first_in_session else VIDEO_LOAD_TIMEOUT_SEC
    if not wait_until_js(driver, VIDEO_LOADED_JS, timeout=load_timeout,
                         heartbeat=HEARTBEAT_SEC, worker_id=worker_id):
        log(worker_id, f"  ! Video did not load in time - skipping {video_name}")
        return {"ok": False, "name": video_name, "reason": "video load timeout"}

    trim_info = driver.execute_script(SET_TRIM_JS, config.TRIM_START_RATIO, config.TRIM_END_RATIO)
    log(worker_id, f"  Trim set: {trim_info}")
    time.sleep(0.5)

    try:
        convert_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(),'Convert to animation')]"))
        )
        safe_click(driver, convert_btn, worker_id=worker_id)
    except Exception:
        log(worker_id, f"  ! No 'Convert to animation' button - skipping {video_name}")
        return {"ok": False, "name": video_name, "reason": "no convert button"}

    log(worker_id, "  Processing (pose extraction)...")
    if not wait_until_js(driver, ANIMATION_READY_JS, timeout=PER_VIDEO_TIMEOUT_SEC,
                         poll=2.0, heartbeat=HEARTBEAT_SEC, worker_id=worker_id):
        log(worker_id, f"  ! Processing timed out for {video_name}")
        return {"ok": False, "name": video_name, "reason": "processing timeout"}

    result = driver.execute_async_script(FINALIZE_EXPORT_JS)
    log(worker_id, f"  -> {result}")
    if result and result.get("ok") and result.get("trackCount", 0) == 0:
        log(worker_id, "  !! WARNING: trackCount is 0 - this GLB will look like an "
                       "unanimated avatar. The bind step likely failed silently.")
    time.sleep(2)  # let the download start before moving on
    return result


def worker_run(worker_id, video_list, download_folder):
    """Process video_list in CHUNK_SIZE browser sessions, restarting between."""
    results = []
    chunks = [video_list[i:i + config.CHUNK_SIZE]
              for i in range(0, len(video_list), config.CHUNK_SIZE)]

    for chunk_idx, chunk_videos in enumerate(chunks, start=1):
        log(worker_id, f"=== chunk {chunk_idx}/{len(chunks)} "
                       f"({len(chunk_videos)} video(s)) - fresh browser ===")
        driver = build_driver(download_folder, worker_id=worker_id, window_index=worker_id - 1)
        wait = WebDriverWait(driver, 60)
        try:
            if not start_session(driver, wait, chunk_videos, worker_id=worker_id):
                log(worker_id, "  Could not start this chunk's session, skipping its videos.")
                results.extend({"ok": False, "name": v, "reason": "session start failed"}
                               for v in chunk_videos)
                continue
            for i in range(len(chunk_videos)):
                results.append(process_video(driver, wait, i, is_first_in_session=(i == 0),
                                             worker_id=worker_id))
        finally:
            driver.quit()
    return results


# --------------------------------------------------------------------------- #
# One category folder
# --------------------------------------------------------------------------- #
def animate_folder(video_folder, download_folder):
    """Animate every .mp4 in video_folder whose .glb isn't already in
    download_folder. Returns the list of per-video result dicts."""
    os.makedirs(download_folder, exist_ok=True)
    all_videos = sorted(glob.glob(os.path.join(video_folder, "*.mp4")))
    if not all_videos:
        print(f"No .mp4 files found in {video_folder}")
        return []

    # RESUME: skip any video that already has a matching .glb.
    videos, skipped = [], []
    for video_path in all_videos:
        base = os.path.splitext(os.path.basename(video_path))[0]
        if os.path.exists(os.path.join(download_folder, base + ".glb")):
            skipped.append(os.path.basename(video_path))
        else:
            videos.append(video_path)

    if skipped:
        print(f"Skipping {len(skipped)} video(s) that already have a .glb in {download_folder}.")
    if not videos:
        print("Nothing to animate - every video already has a matching .glb.")
        return []

    num_workers = max(1, min(config.NUM_WORKERS, len(videos)))
    partitions = [videos[w::num_workers] for w in range(num_workers)]
    print(f"{len(videos)} video(s) to animate. {num_workers} browser worker(s), "
          f"{config.CHUNK_SIZE} videos per session.")

    all_results = []
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(worker_run, w + 1, part, download_folder): w + 1
                   for w, part in enumerate(partitions) if part}
        for future in as_completed(futures):
            wid = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as e:
                log(wid, f"Worker crashed: {e}")

    ok = sum(1 for r in all_results if r.get("ok"))
    animated = sum(1 for r in all_results if r.get("ok") and r.get("trackCount", 0) > 0)
    print(f"Category done: {ok}/{len(all_results)} exported, {animated} with motion data.")
    return all_results


def animate_all(categories=None):
    """Animate every category in the config (or a passed-in dict)."""
    categories = categories if categories is not None else config.CATEGORIES
    for category_url in categories:
        print(f"\n===== ANIMATE: {category_slug(category_url)} =====")
        animate_folder(videos_dir_for(category_url), animations_dir_for(category_url))


if __name__ == "__main__":
    animate_all()
    print("\nAnimation phase done.")
