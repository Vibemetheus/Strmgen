import re
import shutil

from typing import Optional
from pathlib import Path

from opensubtitlescom import OpenSubtitles
from config import settings
from utils import clean_name, safe_mkdir, ensure_str
from log import setup_logger
logger = setup_logger(__name__)

_download_limit_reached = False  # global flag

sub_client: Optional[OpenSubtitles] = None
if (
    settings.opensubtitles_download
    and settings.opensubtitles_app_name
    and settings.opensubtitles_username
    and settings.opensubtitles_password
):
    sub_client = OpenSubtitles(settings.opensubtitles_app_name, settings.opensubtitles_api_key)
    try:
        sub_client.login(settings.opensubtitles_username, settings.opensubtitles_password)
    except Exception as e:
        logger.warning(f"[SUB] OpenSubtitles login failed: {e}")
        sub_client = None

def _download_and_write(params: dict, filename: str, folder: Path) -> None:
    global _download_limit_reached

    if _download_limit_reached:
        logger.info("[SUB] ⏭️ Skipping subtitle download: daily limit already reached.")
        return

    if not sub_client:
        logger.warning("[SUB] OpenSubtitles client is not initialized.")
        return

    safe_mkdir(folder)

    try:
        logger.info(f"[SUB] Searching for subtitles with: {params}")
        resp = sub_client.search(**params)
        results = getattr(resp, "data", None)
        if not results:
            logger.info("[SUB] No subtitle results found.")
            return

        best = max(results, key=lambda s: getattr(s, "download_count", 0))
        sub_id = getattr(best, "id", None)
        count = getattr(best, "download_count", 0)

        if not sub_id:
            logger.warning("[SUB] ❌ Best subtitle result missing 'id'; skipping download.")
            return

        output_path = folder / filename
        logger.info(f"[SUB] Downloading subtitle ID: {sub_id} with {count} downloads")

        # Download subtitle to temp file
        sub_path = sub_client.download_and_save(best)

        if not Path(sub_path).exists():
            logger.error(f"[SUB] ❌ Downloaded subtitle not found at: {sub_path}")
            return

        # Move to desired filename and delete original
        shutil.copy(sub_path, output_path)
        Path(sub_path).unlink(missing_ok=True)

        logger.info(f"[SUB] ✅ Subtitle saved as: {output_path}")

    except Exception as e:
        if "Download limit reached" in str(e) or "406" in str(e):
            _download_limit_reached = True
            logger.warning("[SUB] ❌ Subtitle download blocked (quota or bad format). Skipping further attempts this run.")
        else:
            logger.exception(f"[SUB] ⚠️ Failed to download/save subtitles: {e}")


def _normalize_srt(content: str) -> str:
    """
    Normalize SRT content: renumber indexes and ensure Emby-compatible structure.
    """
    # Split subtitle blocks using double line breaks
    blocks = re.split(r'\r?\n\r?\n', content.strip())
    normalized = []

    index = 1
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) >= 2 and "-->" in lines[0]:  # missing index line
            timestamp = lines[0]
            text = lines[1:]
        elif len(lines) >= 3 and "-->" in lines[1]:  # valid block
            timestamp = lines[1]
            text = lines[2:]
        else:
            continue  # skip malformed

        normalized.append(f"{index}\n{timestamp}\n" + "\n".join(text))
        index += 1

    return "\n\n".join(normalized) + "\n"



def download_movie_subtitles(meta: dict, folder: Path, tmdb_id: Optional[str] = None) -> None:
    if not settings.opensubtitles_download or not meta:
        return
    filename = f"{clean_name(meta.get('title', ''))}.en.srt"
    filepath = folder / filename
    if filepath.exists():
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
        return

    params = {"languages": "en"}
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params.update({
            "query": meta.get("title", ""),
            "year": meta.get("release_date", "")[:4]
        })

    _download_and_write(params, filename, folder)


def download_episode_subtitles(show: str, season: int, ep: int, folder: Path, tmdb_id: Optional[str] = None) -> None:
    if not settings.opensubtitles_download or not show:
        return
    filename = f"{clean_name(show)} - S{season:02}E{ep:02}.en.srt"
    filepath = folder / filename
    if filepath.exists():
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
        return

    params = {
        "season_number": season,
        "episode_number": ep,
        "languages": "en"
    }
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params["query"] = show

    _download_and_write(params, filename, folder)