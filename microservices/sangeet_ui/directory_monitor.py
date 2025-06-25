import os
import time

import hashlib # For generating IDs
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3, HeaderNotFoundError
from mutagen.id3 import ID3NoHeaderError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import your database connection and functions
from database.database import get_pg_connection # Corrected import


from logger.log import setup_logger as log

logger = log(__name__)
SUPPORTED_EXTENSIONS = (
    '.mp3', '.flac', '.ogg', '.oga',
    '.m4a', '.aac',
    '.wav',
    '.wma',
    '.opus',
    '.aiff', # Added
    '.alac'  # Added
)
def extract_metadata(filepath):
    """
    Extracts metadata from a song file using mutagen.
    Generates a unique ID for the song.
    Returns a dictionary with metadata or None if extraction fails or not supported.
    """
    try:
        filename_without_ext, ext = os.path.splitext(filepath)
        ext = ext.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            logger.debug(f"Unsupported file extension: {ext} for file {filepath}")
            return None

        # Generate a unique ID based on the filepath (SHA256 hash)
        file_hash_id = hashlib.sha256(filepath.encode('utf-8')).hexdigest()

        meta = {
            'id': file_hash_id, 
            'title': os.path.basename(filename_without_ext), 
            'artist': 'Unknown Artist',
            'album': 'Unknown Album',
            'duration': 0, 
            'genre': 'Unknown Genre', 
            'filepath': filepath, 
            'thumbnail': None 
        }

        audio = None
        try:
            audio = mutagen.File(filepath, easy=True)
        except HeaderNotFoundError:
             logger.warning(f"Mutagen HeaderNotFoundError for {filepath}. Might be corrupt or not an MP3.")
             try:
                 raw_audio = MP3(filepath)
                 if raw_audio and raw_audio.info:
                     meta['duration'] = int(raw_audio.info.length) # type: ignore
                 return meta 
             except Exception:
                 return None 
        except Exception as e:
            logger.error(f"Mutagen could not open or process file {filepath}: {e}")
            # For newly supported types like aiff, alac, specific mutagen exceptions might occur
            # if they are not well-formed or specific loaders are needed beyond easy=True.
            # We still attempt to get basic info.
            pass # Continue to try getting basic info below

        if audio is None: 
            logger.warning(f"Mutagen returned None for {filepath} with easy=True. Trying to get basic info.")
            try:
                raw_audio_info = mutagen.File(filepath) 
                if raw_audio_info and raw_audio_info.info and hasattr(raw_audio_info.info, 'length'):
                    meta['duration'] = int(raw_audio_info.info.length)
            except Exception as e_raw:
                logger.error(f"Error getting raw audio info for {filepath}: {e_raw}")
            
        if audio and audio.tags: 
            meta['title'] = audio.tags.get('title', [meta['title']])[0]
            meta['artist'] = audio.tags.get('artist', [meta['artist']])[0]
            meta['album'] = audio.tags.get('album', [meta['album']])[0]
            meta['genre'] = audio.tags.get('genre', [meta['genre']])[0]

        if audio and audio.info and hasattr(audio.info, 'length'):
            meta['duration'] = int(audio.info.length)
        elif meta['duration'] == 0: 
             logger.warning(f"Could not retrieve duration from audio.info for {filepath}")

        if ext == '.mp3' and (not audio or not audio.tags):
            try:
                mp3_audio = EasyID3(filepath)
                meta['title'] = mp3_audio.get('title', [meta['title']])[0]
                meta['artist'] = mp3_audio.get('artist', [meta['artist']])[0]
                meta['album'] = mp3_audio.get('album', [meta['album']])[0]
                meta['genre'] = mp3_audio.get('genre', [meta['genre']])[0]
            except ID3NoHeaderError:
                logger.warning(f"No ID3 header in MP3 file: {filepath} (EasyID3).")
            except Exception as e_mp3:
                logger.warning(f"Error using EasyID3 for {filepath}: {e_mp3}")
        
        # Add specific handling for other formats if mutagen.easy=True is insufficient
        if ext in ['.wav', '.aiff', '.alac', '.oga', '.opus'] and (not audio or not audio.tags):
            logger.info(f"File {filepath} (type: {ext}) may not have standard tags or they were not read by easy=True.")
            # Duration should ideally still be caught by the raw_audio_info block or audio.info.length

        return meta

    except Exception as e:
        logger.error(f"Overall error extracting metadata for {filepath}: {e}", exc_info=True)
        return None
# --- Database Interaction Functions ---
# These now target the 'local_songs' table and schema.
# The `local_songs` table schema (from database.py):
# CREATE TABLE IF NOT EXISTS local_songs (
#     id TEXT PRIMARY KEY,
#     title TEXT,
#     artist TEXT,
#     album TEXT,
#     path TEXT UNIQUE NOT NULL,
#     duration INTEGER,
#     genre TEXT,
#     thumbnail TEXT
# );

def song_exists_in_db(conn, filepath):
    """Checks if a song with the given filepath (path) already exists in local_songs."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM local_songs WHERE path = %s", (filepath,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking if song exists (path: {filepath}): {e}")
        return True 

def add_song_to_db(conn, metadata):
    """Adds a new song to the local_songs database."""
    if not metadata or 'filepath' not in metadata or 'id' not in metadata:
        logger.warning(f"Attempted to add song with invalid or missing metadata: {metadata}")
        return
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO local_songs (id, title, artist, album, path, duration, genre)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (path) DO NOTHING; 
            """
            cur.execute(sql, (
                metadata['id'],
                metadata.get('title', 'Unknown Title'),
                metadata.get('artist', 'Unknown Artist'),
                metadata.get('album', 'Unknown Album'),
                metadata['filepath'], 
                metadata.get('duration', 0),
                metadata.get('genre', 'Unknown Genre'),
            ))
            conn.commit()
            logger.info(f"Added song to DB: {metadata['filepath']}")
    except Exception as e:
        logger.error(f"Error adding song {metadata.get('filepath')} to DB: {e}", exc_info=True)
        if conn and not conn.closed: conn.rollback()

def remove_song_from_db(conn, filepath):
    """Removes a song from the local_songs database based on its filepath (path)."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM local_songs WHERE path = %s", (filepath,))
            conn.commit()
            logger.info(f"Removed song from DB: {filepath}")
    except Exception as e:
        logger.error(f"Error removing song {filepath} from DB: {e}", exc_info=True)
        if conn and not conn.closed: conn.rollback()

def update_song_in_db(conn, metadata):
    """Updates an existing song's metadata in the local_songs database."""
    if not metadata or 'filepath' not in metadata or 'id' not in metadata:
        logger.warning(f"Attempted to update song with invalid or missing metadata: {metadata}")
        return
    try:
        with conn.cursor() as cur:
            sql = """
                UPDATE local_songs
                SET id = %s, title = %s, artist = %s, album = %s, duration = %s, genre = %s
                WHERE path = %s;
            """
            cur.execute(sql, (
                metadata['id'],
                metadata.get('title', 'Unknown Title'),
                metadata.get('artist', 'Unknown Artist'),
                metadata.get('album', 'Unknown Album'),
                metadata.get('duration', 0),
                metadata.get('genre', 'Unknown Genre'),
                metadata['filepath'] 
            ))
            conn.commit()
            logger.info(f"Updated song in DB: {metadata['filepath']}")
    except Exception as e:
        logger.error(f"Error updating song {metadata.get('filepath')} in DB: {e}", exc_info=True)
        if conn and not conn.closed: conn.rollback()

# --- Watchdog Event Handler ---
class SongFileEventHandler(FileSystemEventHandler):
    def __init__(self, db_connection):
        super().__init__()
        self.db_conn = db_connection
        # Assuming database schema (local_songs table) is initialized by the main application
        # (e.g., sangeet_ui_server.py calling init_postgres_db())

    def _process_file(self, filepath, action="add"):
        # Check connection before processing
        if self.db_conn is None or self.db_conn.closed:
            logger.warning("DB connection is closed or None in _process_file. Attempting to reconnect.")
            try:
                self.db_conn = get_pg_connection()
                logger.info("Successfully reconnected to DB in _process_file.")
            except Exception as e:
                logger.error(f"Failed to reconnect to DB in _process_file: {e}. Skipping file processing.")
                return

        if action != "delete" and not os.path.exists(filepath):
            logger.info(f"File no longer exists, skipping processing for {action}: {filepath}")
            if song_exists_in_db(self.db_conn, filepath): # Check existence before removing
                 remove_song_from_db(self.db_conn, filepath)
            return

        _ , ext = os.path.splitext(filepath)
        if ext.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug(f"Ignoring file with unsupported extension {ext}: {filepath}")
            return

        logger.info(f"Processing {action} for: {filepath}")
        
        if action == "delete":
            if song_exists_in_db(self.db_conn, filepath):
                remove_song_from_db(self.db_conn, filepath)
            return

        metadata = extract_metadata(filepath) 
        if metadata:
            if action == "add":
                if not song_exists_in_db(self.db_conn, filepath):
                    add_song_to_db(self.db_conn, metadata)
                else: 
                    update_song_in_db(self.db_conn, metadata)
                    logger.info(f"File path already in DB, metadata updated: {filepath}")
            elif action == "modify":
                if song_exists_in_db(self.db_conn, filepath):
                    update_song_in_db(self.db_conn, metadata)
                else:
                    add_song_to_db(self.db_conn, metadata)
                    logger.info(f"Modified file was not in DB, added: {filepath}")
        else:
            logger.warning(f"Could not extract metadata for {filepath}. Removing if exists in DB.")
            if song_exists_in_db(self.db_conn, filepath):
                remove_song_from_db(self.db_conn, filepath)

    def on_created(self, event):
        if not event.is_directory:
            self._process_file(event.src_path, action="add")

    def on_deleted(self, event):
        if not event.is_directory:
            self._process_file(event.src_path, action="delete")

    def on_modified(self, event):
        if not event.is_directory:
            # Ensure file still exists before processing modify, could have been a temp file then deleted
            if os.path.exists(event.src_path):
                 self._process_file(event.src_path, action="modify")
            else: # If modified then quickly deleted, treat as delete
                 self._process_file(event.src_path, action="delete")


    def on_moved(self, event):
        if not event.is_directory:
            # Order matters: remove old path first, then add new path
            self._process_file(event.src_path, action="delete")
            # Ensure destination path exists before adding
            if os.path.exists(event.dest_path):
                self._process_file(event.dest_path, action="add")
            else:
                logger.warning(f"Moved event: destination path {event.dest_path} does not exist. Not adding.")
        else: # Directory moved
            logger.info(f"Directory moved: {event.src_path} to {event.dest_path}. Full rescan might be needed for contents if not individually reported.")
            # For simplicity, we are relying on individual file events for files within moved directories.
            # A more robust solution might trigger a targeted rescan of event.dest_path.


def initial_scan(paths_to_watch, db_conn):
    logger.info(f"Starting initial scan of music directories: {paths_to_watch}")
    all_found_filepaths_in_scan = set()

    for path_to_watch in paths_to_watch:
        if not os.path.isdir(path_to_watch):
            logger.warning(f"Initial scan: Path is not a directory, skipping: {path_to_watch}")
            continue
        for root, _, files in os.walk(path_to_watch):
            for filename in files:
                filepath = os.path.join(root, filename)
                all_found_filepaths_in_scan.add(filepath) # Add all files found

                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in SUPPORTED_EXTENSIONS:
                    if db_conn is None or db_conn.closed: # Check connection
                        logger.warning("DB connection closed during initial scan. Attempting reconnect.")
                        try:
                            db_conn = get_pg_connection()
                            logger.info("DB reconnected during initial scan.")
                        except Exception as e:
                            logger.error(f"Failed to reconnect DB in initial_scan: {e}. Skipping rest of scan for this path.")
                            break # Stop processing this path_to_watch
                    
                    metadata = extract_metadata(filepath)
                    if metadata:
                        if not song_exists_in_db(db_conn, filepath):
                            add_song_to_db(db_conn, metadata)
                        else: 
                            update_song_in_db(db_conn, metadata) # Update if exists, ensures metadata is fresh
                    else:
                        logger.warning(f"Initial scan: Could not extract metadata for {filepath}. Skipped.")
                # else: # No need to log every non-supported file during initial scan unless debugging
                #     logger.debug(f"Initial scan: Skipping unsupported file type {filepath}")
            if db_conn and db_conn.closed: # If connection closed during file walk, break outer loop too
                break
    
    logger.info("Initial scan: Verifying DB against found files...")
    if db_conn is None or db_conn.closed:
        logger.error("Initial scan: DB connection not available for verification step.")
        return

    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT path FROM local_songs") 
            db_filepaths = {row[0] for row in cur.fetchall()}

        paths_to_remove_from_db = set()
        # Normalize paths for comparison
        normalized_paths_to_watch = [os.path.normpath(p) for p in paths_to_watch if os.path.isdir(p)]

        for db_filepath in db_filepaths:
            # Check if the song from DB is within any of the currently monitored root paths
            # and also ensure it was NOT found in the current scan of those paths
            normalized_db_filepath = os.path.normpath(db_filepath)
            in_monitored_scope = any(
                normalized_db_filepath.startswith(monitored_path)
                for monitored_path in normalized_paths_to_watch
            )
            
            if in_monitored_scope and db_filepath not in all_found_filepaths_in_scan:
                # This means the file is in a monitored directory according to DB, but not found on disk.
                paths_to_remove_from_db.add(db_filepath)
        
        for path_to_remove in paths_to_remove_from_db:
            logger.info(f"Initial scan: Song from DB no longer in file system (or unsupported): {path_to_remove}. Removing.")
            remove_song_from_db(db_conn, path_to_remove)

    except Exception as e:
        logger.error(f"Error during DB cleanup in initial scan: {e}", exc_info=True)
    logger.info("Initial scan completed.")


def start_monitoring(paths_to_watch):
    db_conn = None
    try:
        db_conn = get_pg_connection() # Corrected function name
        if db_conn is None:
            logger.error("Failed to get database connection for monitor. Monitoring cannot start.")
            return

        # Schema initialization is expected to be handled by the main application
        # For example, sangeet_ui_server.py calls init_postgres_db() at startup.

        initial_scan(paths_to_watch, db_conn)

        event_handler = SongFileEventHandler(db_conn)
        observer = Observer()
        actual_paths_monitored = 0
        for path in paths_to_watch:
            if os.path.isdir(path): # Check if path is a directory
                observer.schedule(event_handler, path, recursive=True)
                logger.info(f"Scheduled monitoring for path: {path}")
                actual_paths_monitored +=1
            else:
                logger.warning(f"Path not found or not a directory, cannot monitor: {path}")
        
        if actual_paths_monitored == 0:
            logger.error("No valid paths to monitor. Observer not started.")
            if db_conn and not db_conn.closed: db_conn.close()
            return

        observer.start()
        logger.info(f"Directory monitoring started for {actual_paths_monitored} path(s).")
        try:
            while True:
                time.sleep(5) 
                if db_conn is None or db_conn.closed: # Check if connection is closed or None
                    logger.warning("Database connection lost by monitor's main loop. Attempting to reconnect...")
                    # Close potentially broken connection before reassigning
                    if db_conn:
                        try:
                            db_conn.close()
                        except Exception: pass # Ignore errors on closing a bad connection
                    
                    new_db_conn = get_pg_connection() # Corrected function name
                    if new_db_conn and not new_db_conn.closed:
                        db_conn = new_db_conn
                        event_handler.db_conn = db_conn # Update handler's connection
                        logger.info("Monitor successfully reconnected to the database.")
                    else:
                        logger.error("Monitor failed to reconnect to the database. Stopping observer.")
                        if new_db_conn: new_db_conn.close() # Ensure new connection is closed if unusable
                        break 
        except KeyboardInterrupt:
            logger.info("Directory monitoring stopped by user.")
        except Exception as e:
            logger.error(f"An error occurred in monitoring loop: {e}", exc_info=True)
        finally:
            observer.stop()
            observer.join()
            if db_conn and not getattr(db_conn, 'closed', True):
                db_conn.close()
            logger.info("Directory monitoring has been shut down.")
    except Exception as e:
        logger.critical(f"CRITICAL - Failed to start or run directory monitoring: {e}", exc_info=True)
        if db_conn and not getattr(db_conn, 'closed', True): # Ensure db_conn is not None before checking 'closed'
            db_conn.close()

if __name__ == '__main__':
    test_music_paths = ["./sangeet_songs_test/user_music", "./sangeet_songs_test/local_music"]
    for p in test_music_paths:
        os.makedirs(p, exist_ok=True)
        logger.info(f"Ensured dummy directory for testing: {p}")
    
    logger.info(f"Starting STANDALONE monitoring for paths: {test_music_paths}")
    logger.warning("Ensure your database connection (in database.database.py and config) is correctly configured for this standalone test.")
    # For standalone test, ensure database schema exists
    try:
        from database.database import init_postgres_db
        conn_test = get_pg_connection()
        if conn_test:
            # In a real standalone test, you might want to ensure tables are created.
            # init_postgres_db() # Call this if you want the monitor to also handle schema setup when run alone.
            # However, for integration, sangeet_ui_server.py handles this.
            logger.info("Standalone: Database connection successful. Schema init should be handled by main app or uncommented here for pure standalone.")
            conn_test.close()
        else:
            logger.error("Standalone: Failed to connect to database for pre-check.")
    except ImportError:
        logger.error("Standalone: Could not import database.database to pre-check connection.")
    except Exception as e:
        logger.error(f"Standalone: Error during database pre-check: {e}")

    start_monitoring(test_music_paths)