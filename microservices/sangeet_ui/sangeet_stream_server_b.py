# BOTTLE IMPORTS: Replace Flask imports with Bottle's
from bottle import Bottle, static_file, request, response, abort

from utils import util
from functools import wraps
# BOTTLE: CORS is handled by a hook, so no special import is needed
import redis
from database.database import get_pg_connection

from dotenv import load_dotenv
import psycopg2
import os

from logger.log import setup_logger as log

# BOTTLE CHANGE: Use Bottle() instead of Flask()
stream_app = Bottle()

# BOTTLE CHANGE: CORS hook replaces the Flask-CORS extension
@stream_app.hook('after_request')
def enable_cors():
    """Add headers to enable CORS."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'

# --- Framework-agnostic code requires no changes ---
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
load_dotenv(dotenv_path=os.path.join(os.getcwd() , "config" , ".env"))
logger = log(__name__)

# This cache variable should be defined globally
local_songs_data_cache = {}

def load_local_songs_from_db():
    """Load songs from PostgreSQL 'local_songs' table into the global cache. (No changes needed)"""
    global local_songs_data_cache
    logger.info("Attempting to load local songs from PostgreSQL...")
    temp_cache = {}
    conn = None
    try:
        conn = get_pg_connection()
        # This requires `DictCursor` which is part of `psycopg2.extras`
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, title, artist, album, path, duration, genre FROM local_songs")
            rows = cur.fetchall()
            for row in rows:
                if row['path'] and os.path.exists(row['path']):
                    temp_cache[row['id']] = dict(row) # Simpler conversion
                    # Keep original logic for safety
                    temp_cache[row['id']]['duration'] = int(row['duration']) if row['duration'] is not None else 0
                else:
                    logger.warning(f"Local song DB entry {row['id']} has missing/invalid path: {row.get('path')}. Skipping.")
        local_songs_data_cache = temp_cache
        logger.info(f"Loaded {len(local_songs_data_cache)} songs from PostgreSQL 'local_songs' table.")
    except psycopg2.Error as e:
        logger.error(f"Error loading local songs from PostgreSQL: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in load_local_songs_from_db: {e}")
    finally:
        if conn:
            conn.close()
    return local_songs_data_cache

# ... (commented out code is omitted for brevity) ...

@stream_app.route("/stream-server/api/stream/<song_id>/<user_id>")
def api_stream(song_id , user_id):
    """
    Returns the appropriate streaming URL for a given song_id (local or YouTube).
    """
    # --- Handle Local Song ---
    if song_id.startswith("local-"):
        local_songs_cache = load_local_songs_from_db()
        if song_id in local_songs_cache:
            if os.path.exists(local_songs_cache[song_id].get("path", "")):
                logger.info(f"Providing local stream URL for {song_id}")
                return { "local": True, "url": f"/api/stream-local/{song_id}" }
            else:
                logger.error(f"Local song file path missing for ID {song_id}")
                # BOTTLE CHANGE: Set status and return dict instead of jsonify
                response.status = 404
                return {"error": "Local file not found on server"}
        else:
            logger.error(f"Local song ID {song_id} not found in cache")
            response.status = 404
            return {"error": "Local song metadata not found"}
    elif song_id.startswith("uls-"):
        try:
            logger.info(f"Providing ULS stream URL for '{song_id}'")
            return { "local": False, "url": f"/api/v1/stream-uls/{song_id}" }
        except Exception as e:
            print(e)
            # BOTTLE CHANGE: Use Bottle's abort
            abort(500, "An internal server error occurred.")

    # --- Handle YouTube Song ---
    else:
        quality = util.get_stream_quality(user_id)
        filepath = util.get_song_filepath(song_id, quality)
        if os.path.exists(filepath):
            logger.info(f"Providing YouTube stream URL for {song_id} at quality '{quality}'")
            return { "local": False, "url": f"/api/stream-file/{song_id}" }
        else:
            # BOTTLE CHANGE: Return a status code directly
            response.status = 404
            return "File not found for specified quality."


@stream_app.route('/api/v1/stream-uls/<song_id:re:uls-.+>')
def stream_user_local_song(song_id):
    """ Streams a locally stored song if the ID starts with 'uls-'. """
    # BOTTLE CHANGE: The prefix check can be done with a route filter `<song_id:re:uls-.+>`
    # if not song_id.startswith('uls-'):
    #     abort(404, "Resource not found or invalid ID format.")

    conn = None
    try:
        conn = get_pg_connection()
        # NOTE: Assumes default cursor is fine, as DictCursor wasn't used in original.
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM uls_songs WHERE id = %s AND is_deleted = FALSE", (song_id,))
            result = cur.fetchone()

        if not result:
            abort(404, f"Song with ID '{song_id}' not found.")

        file_path = result[0]
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            abort(404, "File associated with this ID is missing on the server.")

        # BOTTLE CHANGE: Use static_file instead of send_file
        # It requires a root directory and a filename separately.
        # Default behavior is to stream for playback (inline).
        root_dir = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        return static_file(filename, root=root_dir)

    except Exception as e:
        print(e)
        abort(500, "An internal server error occurred.")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # BOTTLE CHANGE: Adding debug and reloader is good practice for development
    stream_app.run(host="localhost", port=2300, debug=True, reloader=True)