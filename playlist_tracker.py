import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yt_dlp


BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.jsonc"

REPORTS_DIR = BASE_DIR / "reports"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        content = file.read()

    content = re.sub(
        r'("(?:\\.|[^"\\])*")|//.*',
        lambda match: match.group(1) if match.group(1) else "",
        content,
    )

    return json.loads(content)


def get_playlist_id(url):
    parsed_url = urlparse(url)

    if parsed_url.hostname not in ("youtube.com", "www.youtube.com"):
        raise ValueError("The URL is not a YouTube URL.")

    playlist_id = parse_qs(parsed_url.query).get("list")

    if not playlist_id:
        raise ValueError("No playlist ID was found in the URL.")

    return playlist_id[0]


def get_playlist(playlist_url):
    options = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(playlist_url, download=False)


def sanitize_folder_name(name):
    """Make a playlist name safe to use as a Windows folder name."""
    name = name.strip()

    # Replace characters that are not allowed in Windows filenames.
    name = re.sub(r'[<>:"/\\|?*]', "_", name)

    # Replace control characters.
    name = re.sub(r"[\x00-\x1f]", "_", name)

    # Windows does not allow folder names ending in a space or period.
    name = name.rstrip(" .")

    if not name:
        name = "Unnamed Playlist"

    # Windows reserved device names.
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    if name.upper() in reserved_names:
        name = f"_{name}"

    return name


def get_unique_folder_name(playlist_name, playlist_id, existing_path=None):
    """
    Return a folder name based on the playlist name.

    If another playlist already uses the same folder name,
    append the playlist ID to keep the folders separate.
    """
    base_name = sanitize_folder_name(playlist_name)
    candidate = REPORTS_DIR / base_name

    if not candidate.exists() or candidate == existing_path:
        return base_name

    existing_id = read_playlist_id(candidate / "titles.txt")

    if existing_id == playlist_id:
        return base_name

    return f"{base_name} ({playlist_id})"


def read_playlist_id(titles_file):
    """Read the playlist ID stored at the top of titles.txt."""
    if not titles_file.exists():
        return None

    with open(titles_file, "r", encoding="utf-8") as file:
        first_line = file.readline().strip()

    prefix = "PLAYLIST ID: "

    if first_line.startswith(prefix):
        return first_line[len(prefix):].strip()

    return None


def find_playlist_folder(playlist_id):
    """
    Search all report folders for a matching playlist ID.
    """
    if not REPORTS_DIR.exists():
        return None

    for folder in REPORTS_DIR.iterdir():
        if not folder.is_dir():
            continue

        titles_file = folder / "titles.txt"

        if read_playlist_id(titles_file) == playlist_id:
            return folder

    return None


def get_playlist_folder(playlist_name, playlist_id):
    """
    Find the existing playlist folder by playlist ID.

    If the playlist already exists but its name changed,
    rename the folder to the new playlist name.

    If the playlist is new, create a new folder.
    """
    existing_folder = find_playlist_folder(playlist_id)

    new_folder_name = get_unique_folder_name(
        playlist_name,
        playlist_id,
        existing_path=existing_folder,
    )

    desired_folder = REPORTS_DIR / new_folder_name

    if existing_folder is not None:

        if existing_folder != desired_folder:
            existing_folder.rename(desired_folder)

        return desired_folder

    desired_folder.mkdir(parents=True, exist_ok=True)

    return desired_folder


def read_titles(titles_file):
    titles = {}

    if not titles_file.exists():
        return titles

    with open(titles_file, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            # Ignore the playlist ID header.
            if line.startswith("PLAYLIST ID:"):
                continue

            if not line or "|" not in line:
                continue

            video_id, title = line.split("|", 1)

            titles[video_id.strip()] = title.strip()

    return titles


def read_history(history_file):
    history = {}

    if not history_file.exists():
        return history

    with open(history_file, "r", encoding="utf-8") as file:
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


def write_history(history, history_file):
    with open(history_file, "w", encoding="utf-8") as file:
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


def write_titles(videos, old_titles, titles_file, playlist_id):
    with open(titles_file, "w", encoding="utf-8") as file:

        file.write(f"PLAYLIST ID: {playlist_id}\n\n")

        for video_id, current_title in videos.items():

            if current_title is None:
                previous_title = get_previous_title(
                    old_titles.get(video_id)
                )

                if previous_title and previous_title != "(unknown title)":
                    title = f"{previous_title} (DELETED)"
                else:
                    title = "(unknown title) (DELETED)"

            else:
                title = current_title

            file.write(f"{video_id} | {title}\n")


def read_deleted(deleted_file):
    unavailable = {}
    removed = {}

    if not deleted_file.exists():
        return unavailable, removed

    with open(deleted_file, "r", encoding="utf-8") as file:
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


def write_deleted(unavailable, removed, deleted_file):
    with open(deleted_file, "w", encoding="utf-8") as file:

        file.write("=" * 60 + "\n")
        file.write("UNAVAILABLE VIDEOS\n")
        file.write("=" * 60 + "\n\n")

        if unavailable:
            for video_id, title in unavailable.items():
                file.write(f"{video_id} | {title}\n")
        else:
            file.write("(none)\n")

        file.write("\n\n")

        file.write("=" * 60 + "\n")
        file.write("REMOVED FROM PLAYLIST\n")
        file.write("=" * 60 + "\n\n")

        if removed:
            for video_id, title in removed.items():
                file.write(f"{video_id} | {title}\n")
        else:
            file.write("(none)\n")


def migrate_legacy_reports(playlist_folder):
    """
    Move the old single-playlist report files from reports/
    into the playlist folder if they still exist there.

    This preserves existing tracking data when upgrading
    from the old single-playlist version.
    """
    legacy_files = (
        REPORTS_DIR / "titles.txt",
        REPORTS_DIR / "history.txt",
        REPORTS_DIR / "deleted.txt",
    )

    for legacy_file in legacy_files:

        if not legacy_file.exists():
            continue

        destination = playlist_folder / legacy_file.name

        if not destination.exists():
            legacy_file.rename(destination)


def process_playlist(playlist_url):
    playlist_id = get_playlist_id(playlist_url)

    print(f"Playlist ID: {playlist_id}")
    print()
    print("Reading playlist...")

    playlist = get_playlist(playlist_url)

    playlist_name = playlist.get("title")

    if not playlist_name:
        playlist_name = f"Playlist {playlist_id}"

    playlist_folder = get_playlist_folder(
        playlist_name,
        playlist_id,
    )

    # Handle files from the old single-playlist version.
    migrate_legacy_reports(playlist_folder)

    titles_file = playlist_folder / "titles.txt"
    history_file = playlist_folder / "history.txt"
    deleted_file = playlist_folder / "deleted.txt"

    playlist_entries = playlist.get("entries", [])

    # Keep playlist order while using the video ID as the key.
    current_videos = {}

    for video in playlist_entries:

        video_id = video.get("id")
        title = video.get("title")

        if title is not None:
            title = title.strip()

        if video_id:
            current_videos[video_id] = title

    print(f"Playlist: {playlist_name}")
    print(f"Found {len(current_videos)} videos.")

    old_titles = read_titles(titles_file)
    history = read_history(history_file)
    unavailable, removed = read_deleted(deleted_file)

    changes = 0

    # ---------------------------------------------------------
    # Detect videos that have disappeared from the playlist.
    # ---------------------------------------------------------

    for video_id, old_value in old_titles.items():

        if video_id not in current_videos:

            title = get_previous_title(old_value)

            # If the video was unavailable when it was removed,
            # move it from unavailable to removed.
            if video_id in unavailable:
                del unavailable[video_id]

            # Don't add the same video twice.
            if video_id not in removed:

                removed[video_id] = (
                    f"{title} (DELETED)"
                    if old_value.endswith(" (DELETED)")
                    else title
                )

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

    write_titles(
        current_videos,
        old_titles,
        titles_file,
        playlist_id,
    )

    write_history(
        history,
        history_file,
    )

    write_deleted(
        unavailable,
        removed,
        deleted_file,
    )

    print()

    if changes:
        print(f"Detected {changes} change(s).")
    else:
        print("No changes detected.")

    print(f"Titles saved to:  {titles_file}")
    print(f"History saved to: {history_file}")
    print(f"Deleted saved to: {deleted_file}")


def main():
    config = load_config()

    playlists = config.get("playlists", [])

    if not isinstance(playlists, list):
        raise ValueError(
            '"playlists" must be a list of YouTube playlist URLs.'
        )

    playlists = [
        url.strip()
        for url in playlists
        if isinstance(url, str) and url.strip()
    ]

    if not playlists:
        raise ValueError("No playlist URLs were configured.")

    REPORTS_DIR.mkdir(exist_ok=True)

    for index, playlist_url in enumerate(playlists):

        if index:
            print()
            print("=" * 60)
            print()

        process_playlist(playlist_url)


if __name__ == "__main__":
    main()