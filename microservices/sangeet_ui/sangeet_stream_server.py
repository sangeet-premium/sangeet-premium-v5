from flask import Flask,  send_file , redirect , Blueprint , session , request , jsonify , url_for , abort



from utils import util
from functools import wraps
from flask_cors import CORS # Import the extension
import redis
from database.database import get_pg_connection

from dotenv import load_dotenv
import psycopg2
import os



from logger.log import setup_logger as log

stream_app = Flask("stream app")
CORS(stream_app)
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
load_dotenv(dotenv_path=os.path.join(os.getcwd() , "config" , ".env"))


logger = log(__name__)





def load_local_songs_from_db():
    """Load songs from PostgreSQL 'local_songs' table into the global cache."""
    global local_songs_data_cache
    logger.info("Attempting to load local songs from PostgreSQL...")
    temp_cache = {}
    conn = None
    try:
        conn = get_pg_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Query does NOT include the thumbnail column anymore
            cur.execute("SELECT id, title, artist, album, path, duration, genre FROM local_songs")
            rows = cur.fetchall()
            for row in rows:
                if row['path'] and os.path.exists(row['path']):
                    temp_cache[row['id']] = {
                        "id": row['id'],
                        "title": row['title'] or "Unknown Title",
                        "artist": row['artist'] or "Unknown Artist",
                        "album": row['album'] or "Unknown Album",
                        "path": row['path'],
                        # Thumbnail is no longer part of this dict
                        "duration": int(row['duration']) if row['duration'] is not None else 0,
                        "genre": row.get('genre')
                    }
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

# @stream_app.route("/stream-server/api/stream/<song_id>/<user_id>")
# def api_stream(song_id , user_id):
#     """
#     Returns the appropriate streaming URL for a given song_id (local or YouTube).
#     Records the song play event.
#     """
#     # user_id = session['user_id']
#     # client_timestamp = request.args.get('timestamp') # Get timestamp from client if provided

#     # # Record the play event (can happen before checking type)
#     # # Consider fetching title/artist here if needed for recording, but might slow down response
#     # # For now, assuming record_song handles fetching details if necessary or uses ID only initially
#     # try:
#     #     util.record_song(song_id, user_id, client_timestamp)
#     # except Exception as record_err:
#     #     logger.error(f"Failed to record song play for {song_id}: {record_err}")
#     #     # Continue to provide stream URL even if recording fails

#     # --- Handle Local Song ---
#     if song_id.startswith("local-"):
#         local_songs_cache = load_local_songs_from_db()
#         if song_id in local_songs_cache:
#             # Check if path exists just in case cache is stale
#             if os.path.exists(local_songs_cache[song_id].get("path", "")):
#                 logger.info(f"Providing local stream URL for {song_id}")
#                 # Point to the dedicated local streaming endpoint
#                 return jsonify({
#                     "local": True,
#                     "url": f"/api/stream-local/{song_id}"
#                 })
#             else:
#                 logger.error(f"Local song file path missing for ID {song_id}, cannot generate stream URL.")
#                 return jsonify({"error": "Local file not found on server"}), 404
#         else:
#             logger.error(f"Local song ID {song_id} not found in cache, cannot generate stream URL.")
#             return jsonify({"error": "Local song metadata not found"}), 404

#     # --- Handle YouTube Song ---
#     else:
#         # Use the utility function to ensure the FLAC file exists or is downloaded
#         flac_path = util.download_flac_pg(song_id, user_id)
#         if not flac_path:
#             logger.error(f"Failed to process YouTube song {song_id} for streaming.")
#             return jsonify({"error": "Failed to prepare YouTube song for streaming"}), 500

#         logger.info(f"Providing YouTube stream URL for {song_id}")
#         # Point to the endpoint that serves downloaded FLAC files
#         return jsonify({
#             "local": False, # Indicate it's not from the user's original local library
#             "url": f"/api/stream-file/{song_id}"
#         })


# In sangeet_stream_server.py

@stream_app.route("/stream-server/api/stream/<song_id>/<user_id>")
def api_stream(song_id , user_id):
    """
    Returns the appropriate streaming URL for a given song_id (local or YouTube).
    This function now checks for file existence before providing a URL for YouTube content.
    """
    # --- Handle Local Song ---
    if song_id.startswith("local-"):
        local_songs_cache = load_local_songs_from_db()
        if song_id in local_songs_cache:
            if os.path.exists(local_songs_cache[song_id].get("path", "")):
                logger.info(f"Providing local stream URL for {song_id}")
                # Point to the dedicated local streaming endpoint
                return jsonify({
                    "local": True,
                    "url": f"/api/stream-local/{song_id}"
                })
            else:
                logger.error(f"Local song file path missing for ID {song_id}, cannot generate stream URL.")
                return jsonify({"error": "Local file not found on server"}), 404
        else:
            logger.error(f"Local song ID {song_id} not found in cache, cannot generate stream URL.")
            return jsonify({"error": "Local song metadata not found"}), 404
    elif song_id.startswith("uls-"):
        conn = None
        try:
           
            logger.info(f"Providing YouTube stream URL for {song_id}'")
            # Point to the endpoint that serves downloaded files
            return jsonify({
                "local": False, # Indicate it's not from the user's original local library
                "url": f"/api/stream-file/{song_id}"
            })

        except Exception as e:

            # Return a generic error to the user
            print(e)
            abort(500, description="An internal server error occurred.")

       

    # --- Handle YouTube Song ---
    else:
        # Get the quality setting for the user
        quality = util.get_stream_quality(user_id)
        # Determine the expected file path based on song_id and quality
        filepath = util.get_song_filepath(song_id, quality)

        # Check if the file for the required quality exists
        if os.path.exists(filepath):
            logger.info(f"Providing YouTube stream URL for {song_id} at quality '{quality}'")
            # Point to the endpoint that serves downloaded files
            return jsonify({
                "local": False, # Indicate it's not from the user's original local library
                "url": f"/api/stream-file/{song_id}"
            })
        else:
            # util.download_flac_pg(song_id, user_id)
            # return jsonify({
            #     "local": False, # Indicate it's not from the user's original local library
            #     "url": f"/api/stream-file/{song_id}"
            # })
            return 404


@stream_app.route('/api/v1/stream-uls/<string:song_id>')
def stream_user_local_song(song_id):
    """
    Streams a locally stored song if the ID starts with 'uls-'.

    This endpoint retrieves the file path of a song from the 'uls_songs'
    database table based on its ID. If the ID is valid and the file exists,
    it streams the file to the client using Flask's `send_file`.

    Args:
        song_id (str): The unique identifier for the song.

    Returns:
        A file stream response on success (200 OK).
        A JSON error message on failure (404 Not Found or 500 Internal Server Error).
    """
    # 1. Validate the prefix of the requested ID
    if not song_id.startswith('uls-'):

        # Use abort() to raise a standard HTTP exception
        abort(404, description="Resource not found or invalid ID format.")

    conn = None
    try:
        # 2. Securely connect to the database
        conn = get_pg_connection()
        with conn.cursor() as cur:
            # 3. Query the database for the file path
            # We also check that the song is not marked as deleted
            cur.execute(
                "SELECT file_path FROM uls_songs WHERE id = %s AND is_deleted = FALSE",
                (song_id,)
            )
            result = cur.fetchone()

        # 4. Check if a record was found
        if not result:
           
            abort(404, description=f"Song with ID '{song_id}' not found.")

        file_path = result[0]

        # 5. Security Check: Ensure the file path exists and is a file
        if not os.path.exists(file_path) or not os.path.isfile(file_path):

            abort(404, description="File associated with this ID is missing on the server.")

    
        
        # 6. Use send_file to stream the song
        # send_file handles MIME type detection, ETag generation, etc.
        # `as_attachment=False` makes it stream for playback in the browser.
        return send_file(file_path, as_attachment=False)

    except Exception as e:
        print(e)
        # Return a generic error to the user
        abort(500, description="An internal server error occurred.")

    finally:
        # Ensure the database connection is always closed
        if conn:
            conn.close()



if __name__ == "__main__":
    stream_app.run(host="localhost", port=2300)