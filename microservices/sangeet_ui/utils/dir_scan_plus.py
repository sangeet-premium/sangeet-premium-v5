

# utils/dir_scan_plus.py

import os
import json
import time
import uuid
import subprocess
import shutil
from pathlib import Path
from typing import Union, List, Tuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv
from threading import Thread, Lock, Event

from mutagen import File, MutagenError
from mutagen.flac import Picture
from mutagen.id3 import APIC

# Assuming database.py is in a 'database' subdirectory
from database.database import get_pg_connection

# --- Configuration (Unchanged) ---
supported_music_formats = [
    ".3gp", ".aa", ".aac", ".aax", ".act", ".aiff", ".alac", ".amr", ".ape", ".au",
    ".awb", ".dss", ".dvf", ".flac", ".gsm", ".iklax", ".ivs", ".m4a", ".m4b",
    ".m4p", ".mmf", ".mov", ".mp3", ".mpc", ".msv", ".nmf", ".ogg", ".oga",
    ".mogg", ".opus", ".ra", ".rm", ".raw", ".rf64", ".sln", ".tta", ".voc",
    ".vox", ".wav", ".wma", ".wv", ".webm", ".8svx", ".cda"
]
FORMAT_PREFERENCE = [
    '.flac', '.wav', '.alac', '.ape', '.aiff', '.wv',
    '.ogg', '.opus', '.mp3', '.m4a', '.aac', '.wma'
]
CWD = Path.cwd()
THUMBNAILS_DIR = CWD / "thumbnails" / "uls"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

def check_ffmpeg():
    if not shutil.which("ffprobe"):
        print("!!! WARNING: ffmpeg (ffprobe) is not installed or not in PATH. Full functionality will be limited.")
        return False
    return True
FFMPEG_AVAILABLE = check_ffmpeg()

def setup_database():
    print("Setting up database schema...")
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS artists (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS albums (id SERIAL PRIMARY KEY, name TEXT NOT NULL, artist_id INTEGER REFERENCES artists(id) ON DELETE SET NULL, UNIQUE(name, artist_id));
                CREATE TABLE IF NOT EXISTS genres (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS uls_songs (
                    id VARCHAR(40) PRIMARY KEY, base_name_key TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL, file_size_bytes BIGINT, title TEXT, track_number TEXT, year INTEGER,
                    duration_seconds FLOAT, thumbnail_path TEXT, added_at TIMESTAMPTZ DEFAULT NOW(),
                    modified_at TIMESTAMPTZ DEFAULT NOW(), is_deleted BOOLEAN DEFAULT FALSE,
                    artist_id INTEGER REFERENCES artists(id) ON DELETE SET NULL,
                    album_id INTEGER REFERENCES albums(id) ON DELETE SET NULL,
                    genre_id INTEGER REFERENCES genres(id) ON DELETE SET NULL);
                CREATE INDEX IF NOT EXISTS idx_songs_artist_id ON uls_songs (artist_id);
                CREATE INDEX IF NOT EXISTS idx_songs_album_id ON uls_songs (album_id);
                CREATE INDEX IF NOT EXISTS idx_songs_is_deleted ON uls_songs (is_deleted);
            """)
            conn.commit()
            print("✅ Database setup complete.")
    finally:
        conn.close()
def generate_unique_id(): return f"uls-{uuid.uuid4()}"
def get_metadata_with_ffprobe(file_path):
    if not FFMPEG_AVAILABLE: return {}
    try:
        command = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        format_data = json.loads(result.stdout).get("format", {})
        tags = {k.lower(): v for k, v in format_data.get("tags", {}).items()}
        return {'title': tags.get('title'), 'artist': tags.get('artist'), 'album': tags.get('album'), 'genre': tags.get('genre'), 'date': tags.get('date', tags.get('creation_time')), 'track': tags.get('track'), 'duration': float(format_data.get('duration', 0.0))}
    except Exception: return {}
def get_file_info(file_path):
    info = {'duration': 0.0}
    try:
        audio = File(file_path)
        if audio and audio.info:
            info['duration'] = audio.info.length
            easy_audio = File(file_path, easy=True)
            info.update({'title': easy_audio.get('title', [None])[0], 'artist': easy_audio.get('artist', [None])[0], 'album': easy_audio.get('album', [None])[0], 'genre': easy_audio.get('genre', [None])[0], 'date': easy_audio.get('date', [None])[0], 'track': easy_audio.get('tracknumber', [None])[0]})
    except MutagenError: pass
    if not any([info.get('title'), info.get('artist')]) or info.get('duration', 0.0) == 0.0:
        ffprobe_meta = get_metadata_with_ffprobe(file_path)
        if ffprobe_meta.get('duration', 0.0) > 0.0: info.update(ffprobe_meta)
    return {k: v for k, v in info.items() if v is not None}
def _extract_and_save_artwork(audio_filepath, song_id):
    target_path = THUMBNAILS_DIR / f"{song_id}.png"
    if target_path.exists(): os.remove(target_path)
    artwork = None
    try:
        audio = File(audio_filepath)
        if 'APIC:' in audio: artwork = audio.get('APIC:').data
        elif 'covr' in audio: artwork = audio.get('covr')[0]
        elif audio.pictures: artwork = audio.pictures[0].data
    except Exception: artwork = None
    if not artwork and FFMPEG_AVAILABLE:
        try:
            command = ['ffmpeg', '-i', audio_filepath, '-an', '-vcodec', 'copy', str(target_path)]
            subprocess.run(command, check=True, capture_output=True, timeout=15)
            if target_path.exists() and target_path.stat().st_size > 0: return str(target_path)
            if target_path.exists(): os.remove(target_path)
            return None
        except Exception:
             if target_path.exists(): os.remove(target_path)
             return None
    if artwork:
        with open(target_path, 'wb') as img_file: img_file.write(artwork)
        return str(target_path)
    return None
def get_local_song_thumbnail_path(song_id: str):
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path, thumbnail_path FROM uls_songs WHERE id = %s AND is_deleted = FALSE", (song_id,))
            result = cur.fetchone()
            if not result: return None
            file_path, thumb_path_from_db = result
            if thumb_path_from_db and os.path.exists(thumb_path_from_db): return thumb_path_from_db
            new_thumb_path = _extract_and_save_artwork(file_path, song_id)
            if new_thumb_path:
                cur.execute("UPDATE uls_songs SET thumbnail_path = %s WHERE id = %s", (new_thumb_path, song_id))
                conn.commit()
            return new_thumb_path
    except Exception as e:
        print(f"An error occurred in get_local_song_thumbnail_path: {e}")
        return None
    finally:
        if conn: conn.close()


# --- Smart Event Handler with Debouncing ---
class MusicDBHandler(FileSystemEventHandler):
    def __init__(self, music_path: str = None, stability_delay: int = 5):
        super().__init__()
        self.music_path = os.path.abspath(music_path) if music_path else None
        
        # --- NEW: Debouncing and Stability Logic ---
        self.stability_delay = stability_delay  # seconds
        self.pending_events = {}
        self.lock = Lock()
        self.processing_thread = Thread(target=self._process_pending_events, daemon=True)
        self.stop_event = Event()
        
        if self.music_path:
            print(f"🎵 Special music_path configured for direct ID mapping: {self.music_path}")

    def start(self):
        """Starts the background processing thread."""
        print(f"⏳ Event processor started. Will wait for {self.stability_delay}s of file inactivity before processing.")
        self.processing_thread.start()

    def stop(self):
        """Stops the background processing thread."""
        self.stop_event.set()
        self.processing_thread.join()
        print("🛑 Event processor stopped.")

    def _queue_event(self, event_type: str, path: str):
        """Adds an event to the pending queue, waiting for stability."""
        # Ignore temporary or unsupported files immediately
        if ".part" in path or Path(path).suffix.lower() not in supported_music_formats:
            return

        with self.lock:
            # Record the event time and initial file stats
            try:
                stat = os.stat(path) if event_type != 'deleted' else None
                self.pending_events[path] = {
                    "type": event_type,
                    "time": time.time(),
                    "size": stat.st_size if stat else None,
                    "mtime": stat.st_mtime if stat else None,
                }
            except FileNotFoundError:
                 # File might be deleted between event and stat call, which is fine
                 if event_type != 'deleted':
                     self.pending_events[path] = {"type": 'deleted', "time": time.time()}

    def _process_pending_events(self):
        """Worker thread target to process events for stable files."""
        while not self.stop_event.is_set():
            stable_events = {}
            with self.lock:
                current_time = time.time()
                # Find events that are old enough to be considered for processing
                for path, event_data in list(self.pending_events.items()):
                    if current_time - event_data["time"] > self.stability_delay:
                        # Check for stability
                        is_stable = False
                        if event_data["type"] == 'deleted':
                            is_stable = True
                        else:
                            try:
                                # A file is stable if its size and mod time haven't changed
                                stat = os.stat(path)
                                if stat.st_size == event_data["size"] and stat.st_mtime == event_data["mtime"]:
                                    is_stable = True
                                else:
                                    # File changed, reset its timer
                                    event_data["time"] = current_time
                                    event_data["size"] = stat.st_size
                                    event_data["mtime"] = stat.st_mtime
                            except FileNotFoundError:
                                # File was deleted while pending, switch to a delete event
                                stable_events[path] = 'deleted'
                                del self.pending_events[path]

                        if is_stable:
                            stable_events[path] = event_data["type"]
                            del self.pending_events[path]
            
            # Process the stable events outside the lock
            for path, event_type in stable_events.items():
                try:
                    if event_type in ('created', 'modified'):
                        print(f"✔️ File '{Path(path).name}' is stable. Processing update...")
                        self._process_update(path)
                    elif event_type == 'deleted':
                        print(f"✔️ File '{Path(path).name}' deletion confirmed. Processing...")
                        self._process_delete(path)
                except Exception as e:
                    print(f"🚨 Error processing stable event for '{path}': {e}")
            
            self.stop_event.wait(2) # Check for stable files every 2 seconds

    # --- Core DB Logic (Unchanged but now called by the processor thread) ---
    def _get_or_create_related_id(self, cur, table, columns, values):
        query = f"SELECT id FROM {table} WHERE " + " AND ".join([f"{col} = %s" for col in columns])
        cur.execute(query, values)
        result = cur.fetchone()
        if result: return result[0]
        insert_cols, placeholders = ", ".join(columns), ", ".join(["%s"] * len(columns))
        query = f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING RETURNING id"
        cur.execute(query, values)
        result = cur.fetchone()
        return result[0] if result else self._get_or_create_related_id(cur, table, columns, values)
    def _handle_thumbnail(self, audio_filepath, song_id): return _extract_and_save_artwork(audio_filepath, song_id)
    def _get_preference_score(self, ext):
        try: return FORMAT_PREFERENCE.index(ext.lower())
        except ValueError: return len(FORMAT_PREFERENCE)
    def _process_update(self, file_path_str):
        file_path = Path(file_path_str)
        base_name_key = str(file_path.with_suffix(''))
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                is_in_music_path = self.music_path and os.path.abspath(file_path_str).startswith(self.music_path)
                if is_in_music_path:
                    cur.execute("SELECT id, file_path FROM uls_songs WHERE base_name_key = %s AND is_deleted = FALSE", (base_name_key,))
                    existing_song = cur.fetchone()
                    if existing_song:
                        existing_ext = Path(existing_song[1]).suffix
                        new_ext = file_path.suffix
                        if self._get_preference_score(new_ext) > self._get_preference_score(existing_ext):
                            print(f"⚖️  Ignoring '{file_path.name}'; a better format is already registered.")
                            return
                    song_id = file_path.stem
                else:
                    cur.execute("SELECT id FROM uls_songs WHERE file_path = %s AND is_deleted = FALSE", (file_path_str,))
                    existing_song = cur.fetchone()
                    song_id = existing_song[0] if existing_song else generate_unique_id()
                info = get_file_info(file_path_str)
                artist_id = self._get_or_create_related_id(cur, 'artists', ('name',), (info.get('artist', 'Unknown Artist'),)) if info.get('artist') else None
                album_id = self._get_or_create_related_id(cur, 'albums', ('name', 'artist_id'), (info.get('album', 'Unknown Album'), artist_id)) if info.get('album') else None
                genre_id = self._get_or_create_related_id(cur, 'genres', ('name',), (info.get('genre', 'Unknown'),)) if info.get('genre') else None
                thumbnail_path = self._handle_thumbnail(file_path_str, song_id)
                song_data = {'id': song_id, 'base_name_key': base_name_key, 'file_name': file_path.name, 'file_path': file_path_str, 'file_size_bytes': file_path.stat().st_size, 'title': info.get('title'), 'track_number': info.get('track'), 'year': int(str(info.get('date', '0'))[:4]) if info.get('date') else None, 'duration_seconds': info.get('duration', 0.0), 'thumbnail_path': thumbnail_path, 'artist_id': artist_id, 'album_id': album_id, 'genre_id': genre_id}
                sql = """
                    INSERT INTO uls_songs (id, base_name_key, file_name, file_path, file_size_bytes, title, track_number, year, duration_seconds, thumbnail_path, artist_id, album_id, genre_id)
                    VALUES (%(id)s, %(base_name_key)s, %(file_name)s, %(file_path)s, %(file_size_bytes)s, %(title)s, %(track_number)s, %(year)s, %(duration_seconds)s, %(thumbnail_path)s, %(artist_id)s, %(album_id)s, %(genre_id)s)
                    ON CONFLICT (base_name_key) DO UPDATE SET
                        file_path = EXCLUDED.file_path, file_name = EXCLUDED.file_name, file_size_bytes = EXCLUDED.file_size_bytes,
                        title = EXCLUDED.title, track_number = EXCLUDED.track_number, year = EXCLUDED.year,
                        duration_seconds = EXCLUDED.duration_seconds, thumbnail_path = EXCLUDED.thumbnail_path,
                        artist_id = EXCLUDED.artist_id, album_id = EXCLUDED.album_id, genre_id = EXCLUDED.genre_id,
                        is_deleted = FALSE, modified_at = NOW();"""
                cur.execute(sql, song_data)
                conn.commit()
                action = "Updated" if existing_song else "Added"
                print(f"💾 {action} '{info.get('title', file_path.name)}' in database.")
        finally:
            conn.close()
    def _process_delete(self, file_path_str):
        file_path = Path(file_path_str)
        base_name_key = str(file_path.with_suffix(''))
        is_in_music_path = self.music_path and os.path.abspath(file_path_str).startswith(self.music_path)
        if is_in_music_path:
            sibling_files = []
            for ext in supported_music_formats:
                sibling = file_path.with_suffix(ext)
                if sibling.exists() and str(sibling) != file_path_str: sibling_files.append(sibling)
            sibling_files.sort(key=lambda p: self._get_preference_score(p.suffix))
            if sibling_files:
                best_fallback_path = str(sibling_files[0])
                print(f"⬇️  File '{file_path.name}' deleted. Falling back to: '{Path(best_fallback_path).name}'.")
                self._process_update(best_fallback_path)
                return
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                key_column = "base_name_key" if is_in_music_path else "file_path"
                key_value = base_name_key if is_in_music_path else file_path_str
                cur.execute(f"SELECT thumbnail_path FROM uls_songs WHERE {key_column} = %s AND is_deleted = FALSE", (key_value,))
                result = cur.fetchone()
                cur.execute(f"UPDATE uls_songs SET is_deleted = TRUE, modified_at = NOW() WHERE {key_column} = %s", (key_value,))
                conn.commit()
                print(f"❌ Marked '{file_path.name}' as deleted in database.")
                if result and result[0] and os.path.exists(result[0]):
                    os.remove(result[0])
                    print(f"🗑️  Deleted thumbnail {os.path.basename(result[0])}")
        finally:
            conn.close()

    # --- Watchdog Event Handlers (Now just queue events) ---
    def on_created(self, event):
        if not event.is_directory:
            print(f"👀 Detected creation: {event.src_path}. Waiting for stability...")
            self._queue_event('created', event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            print(f"👀 Detected modification: {event.src_path}. Waiting for stability...")
            self._queue_event('modified', event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            print(f"👀 Detected deletion: {event.src_path}. Confirming...")
            self._queue_event('deleted', event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            print(f"👀 Detected move: {event.src_path} -> {event.dest_path}. Confirming...")
            self._queue_event('deleted', event.src_path)
            self._queue_event('created', event.dest_path)


# --- UPDATED MONITOR CLASS ---
class Local_songs_mon:
    def __init__(self, directory_paths: Union[str, List[str]], music_path: str = None):
        setup_database()
        if isinstance(directory_paths, str):
            self.directory_paths = [os.path.abspath(directory_paths)]
        else:
            self.directory_paths = [os.path.abspath(p) for p in directory_paths]
        # --- Use the new smart handler ---
        self.event_handler = MusicDBHandler(music_path=music_path)
        self.observer = Observer()

    def _initial_scan(self):
        """Performs a one-time scan of all directories to process existing files."""
        print("\nPerforming initial scan of all monitored directories... This may take a while.")
        total_files = 0
        for path in self.directory_paths:
            print(f"Scanning directory: {path}")
            for root, _, files in os.walk(path):
                for filename in files:
                    if Path(filename).suffix.lower() in supported_music_formats:
                        full_path = os.path.join(root, filename)
                        try:
                            # We can reuse the robust update logic directly here
                            # because these files are assumed to be stable on initial scan.
                            self.event_handler._process_update(full_path)
                            total_files += 1
                        except Exception as e:
                            print(f"Error processing file during initial scan '{full_path}': {e}")
        print(f"✅ Initial scan complete. Processed {total_files} files.")

    def start(self):
        """Performs an initial scan and then starts the real-time monitor."""
        # 1. Perform the one-time scan for existing files
        self._initial_scan()
        
        # 2. Start the background event processor in the handler
        self.event_handler.start()

        # 3. Start the real-time file system monitoring
        print("\n🎶🔍 Starting real-time directory monitoring for:")
        for path in self.directory_paths:
            self.observer.schedule(self.event_handler, path, recursive=True)
            print(f"  -> {path}")
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
        # --- Make sure to stop the handler's thread ---
        self.event_handler.stop()
        print("🛑 Directory monitor stopped.")


# --- get_paths function is unchanged ---
def get_paths(env_path) -> Tuple[List[str], str]:
    load_dotenv(dotenv_path=env_path)
    unique_paths, music_path = set(), os.getenv("MUSIC_PATH")
    if music_path: unique_paths.add(music_path.strip())
    local_songs_str = os.getenv("LOCAL_SONGS_PATH")
    if local_songs_str:
        paths = [path.strip() for path in local_songs_str.split(';')]
        for p in paths:
            if p: unique_paths.add(p)
    valid_paths, validated_music_path = [], None
    print("🔎 Checking for valid paths from .env file...")
    for path in unique_paths:
        if os.path.exists(path):
            print(f"  ✅ Found: {path}")
            valid_paths.append(path)
            if music_path and os.path.abspath(path) == os.path.abspath(music_path):
                validated_music_path = os.path.abspath(path)
        else:
            print(f"  ❌ Warning: Path does not exist and will be ignored: {path}")
    if not valid_paths: print("  ⚠️ No valid paths were found to monitor.")
    return valid_paths, validated_music_path


#usage
# main.py (or your startup script)

# import os
# import time
# # Make sure to import your updated functions
# from dir_scan_plus import Local_songs_mon, get_paths

# if __name__ == "__main__":
#     try:
#         # Define the path to your configuration file
#         config_file_path = os.path.join(os.getcwd(), "configs", "ui", "config.conf")

#         # 1. Get both the list of all paths and the special music_path
#         paths_to_scan, music_dir = get_paths(config_file_path)

#         if not paths_to_scan:
#             print("Aborting: No valid directories to monitor.")
#         else:
#             # 2. Initialize the monitor with both arguments
#             scanner = Local_songs_mon(
#                 directory_paths=paths_to_scan, 
#                 music_path=music_dir
#             )
#             scanner.start()

#             print("\n🚀 Your main application is now running.")
#             print("   (Press Ctrl+C to simulate shutting down the app)")
            
#             while True:
#                 time.sleep(1)

#     except (KeyboardInterrupt, SystemExit):
#         print("\n👋 Main application is shutting down...")
#         if 'scanner' in locals():
#             scanner.stop()
#     except Exception as e:
#         print(f"An unexpected error occurred: {e}")
#         if 'scanner' in locals():
#             scanner.stop()
#     finally:
#         print("✅ Application has shut down gracefully.")