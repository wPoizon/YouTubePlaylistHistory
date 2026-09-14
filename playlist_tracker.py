import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yt_dlp


BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"

REPORTS_DIR = BASE_DIR / "reports"
TITLES_FILE = REPORTS_DIR / "titles.txt"
HISTORY_FILE = REPORTS_DIR / "history.txt"
DELETED_FILE = REPORTS_DIR / "deleted.txt"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_playlist_id(url):
    parsed_url = urlparse(url)

    if parsed_url.hostname not in ("youtube.com", "www.youtube.com"):
        raise ValueError("The URL is not a YouTube URL.")

    playlist_id = parse_qs(parsed_url.query).get("list")

    if not playlist_id:
        raise ValueError("No playlist ID was found in the URL.")

    return playlist_id[0]


def get_playlist_videos(playlist_url):
    options = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        playlist = ydl.extract_info(playlist_url, download=False)

    return playlist.get("entries", [])


def read_titles():
    titles = {}

    if not TITLES_FILE.exists():
        return titles

    with open(TITLES_FILE, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or "|" not in line:
                continue

            video_id, title = line.split("|", 1)
            titles[video_id.strip()] = title.strip()

    return titles


def read_history():
    history = {}

    if not HISTORY_FILE.exists():
        return history

    with open(HISTORY_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    current_video_id = None

    for line in lines:
        line = line.rstrip()

        if not line:
            continue

        if not line.startswith("    "):
            current_video_id = line
            history[current_video_id] = []
            continue

        title = line.strip()

        if title not in ("|", "V"):
            history[current_video_id].append(title)

    return history


def write_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        for video_id, titles in history.items():
            file.write(f"{video_id}\n")

            for index, title in enumerate(titles):
                file.write(f"    {title}\n")

                if index < len(titles) - 1:
                    file.write("        |\n")
                    file.write("        V\n")

            file.write("\n")


def get_previous_title(old_value):
    if old_value is None:
        return None

    if old_value.endswith(" (DELETED)"):
        return old_value[:-10]

    return old_value

def write_titles(videos, old_titles):
    with open(TITLES_FILE, "w", encoding="utf-8") as file:
        for video_id, current_title in videos.items():

            if current_title is None:
                previous_title = get_previous_title(old_titles.get(video_id))

                if previous_title and previous_title != "(unknown title)":
                    title = f"{previous_title} (DELETED)"
                else:
                    title = "(unknown title) (DELETED)"
            else:
                title = current_title

            file.write(f"{video_id} | {title}\n")


def read_deleted():
    unavailable = {}
    removed = {}

    if not DELETED_FILE.exists():
        return unavailable, removed

    with open(DELETED_FILE, "r", encoding="utf-8") as file:
        section = None

        for line in file:
            line = line.strip()

            if line == "UNAVAILABLE VIDEOS":
                section = "unavailable"
                continue

            if line == "REMOVED FROM PLAYLIST":
                section = "removed"
                continue

            if not line or "|" not in line:
                continue

            video_id, title = line.split("|", 1)
            video_id = video_id.strip()
            title = title.strip()

            if section == "unavailable":
                unavailable[video_id] = title
            elif section == "removed":
                removed[video_id] = title

    return unavailable, removed


def write_deleted(unavailable, removed):
    with open(DELETED_FILE, "w", encoding="utf-8") as file:
        file.write("UNAVAILABLE VIDEOS\n\n")

        if unavailable:
            for video_id, title in unavailable.items():
                file.write(f"{video_id} | {title}\n")
        else:
            file.write("(none)\n")

        file.write("\n\n")
        file.write("REMOVED FROM PLAYLIST\n\n")

        if removed:
            for video_id, title in removed.items():
                file.write(f"{video_id} | {title}\n")
        else:
            file.write("(none)\n")


def main():
    config = load_config()

    playlist_url = config["playlist_url"]
    playlist_id = get_playlist_id(playlist_url)

    print(f"Playlist ID: {playlist_id}")
    print()
    print("Reading playlist...")

    playlist_entries = get_playlist_videos(playlist_url)

    # Keep playlist order while using the video ID as the key.
    current_videos = {}

    for video in playlist_entries:
        video_id = video.get("id")
        title = video.get("title")

        if title is not None:
            title = title.strip()

        if video_id:
            current_videos[video_id] = title

    print(f"Found {len(current_videos)} videos.")

    REPORTS_DIR.mkdir(exist_ok=True)

    old_titles = read_titles()
    history = read_history()
    unavailable, removed = read_deleted()

    changes = 0

    # ---------------------------------------------------------
    # Detect videos that have disappeared from the playlist.
    # ---------------------------------------------------------

    for video_id, old_value in old_titles.items():
        if video_id not in current_videos:

            title = get_previous_title(old_value)

            # If the video was unavailable when it was removed,
            # move it from the unavailable section to the removed section.
            if video_id in unavailable:
                del unavailable[video_id]

            # Don't add the same video twice.
            if video_id not in removed:
                removed[video_id] = f"{title} (DELETED)" if old_value.endswith(
                    " (DELETED)"
                ) else title

            changes += 1

    # ---------------------------------------------------------
    # Detect currently unavailable videos.
    # ---------------------------------------------------------

    for video_id, current_title in current_videos.items():

        if current_title is None:
            previous_value = old_titles.get(video_id)
            previous_title = get_previous_title(previous_value)

            if previous_title and previous_title != "(unknown title)":
                title = f"{previous_title} (DELETED)"
            else:
                title = "(unknown title) (DELETED)"

            unavailable[video_id] = title

            # It is currently in the playlist, so it cannot
            # simultaneously be in the removed section.
            removed.pop(video_id, None)

    # ---------------------------------------------------------
    # Detect title changes.
    # ---------------------------------------------------------

    for video_id, current_title in current_videos.items():

        # Unavailable videos do not generate title history.
        if current_title is None:
            continue

        old_value = old_titles.get(video_id)

        if old_value is None:
            continue

        old_title = get_previous_title(old_value)

        # No title change.
        if old_title == current_title:
            continue

        # The video was unavailable and is now available again.
        if old_value.endswith(" (DELETED)"):
            if old_title != "(unknown title)":
                if video_id not in history:
                    history[video_id] = [old_title]

        # Genuine title change.
        else:
            if video_id not in history:
                history[video_id] = [old_title]

            if history[video_id][-1] != current_title:
                history[video_id].append(current_title)
                changes += 1

    write_titles(current_videos, old_titles)
    write_history(history)
    write_deleted(unavailable, removed)

    print()

    if changes:
        print(f"Detected {changes} change(s).")
    else:
        print("No changes detected.")

    print(f"Titles saved to:  {TITLES_FILE}")
    print(f"History saved to: {HISTORY_FILE}")
    print(f"Deleted saved to: {DELETED_FILE}")


if __name__ == "__main__":
    main()