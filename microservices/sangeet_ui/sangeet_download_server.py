


from flask import (Flask, send_file, session, redirect, request, jsonify, url_for)
from database.database import get_pg_connection
import psycopg2.extras # Ensure DictCursor is available
from utils import util
from functools import wraps

import os
from flask_cors import CORS
import subprocess

# Import the Celery app and the task
from celery_app import celery
from tasks import download_youtube_song_task
from logger.log import setup_logger as log

bp = Flask("sangeet_download_server")
logger = log(__name__)
CORS(bp)


@bp.route("/download-server/api/download/<song_id>/<user_id_session>")
def api_download(song_id, user_id_session):
    """
    Handles all song requests by checking for the correct file based on quality settings first.
    If the file doesn't exist, it initiates a download.
    This works for both local files (served as-is) and YouTube downloads (quality-aware).
    """
    conn = None
    # --- Handle local songs first ---
    # For local songs from the user's library, we serve the exact file from the DB path.
    # There is no quality selection for these as they are pre-existing, unique files.
    if song_id.startswith("local-"):
        try:
            conn = get_pg_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM local_songs WHERE id = %s", (song_id,))
                local_song = cur.fetchone()
                if local_song and local_song.get('path') and os.path.exists(local_song['path']):
                    logger.info(f"Serving local library song: {song_id}")
                    # Use the new helper to send the file with correct headers
                    return send_downloadable_file(local_song['path'], local_song)
                else:
                    logger.error(f"Local song '{song_id}' requested but not found in DB or path is invalid.")
                    return jsonify({"error": "Local file not found"}), 404
        except Exception as e:
            logger.error(f"Error processing local song '{song_id}': {e}", exc_info=True)
            return jsonify({"error": "Server error during local song download."}), 500
        finally:
            if conn and not conn.closed:
                conn.close()
    # --- NEW: Correctly handle songs from your local scanner ('uls-') ---
    elif song_id.startswith("uls-"):
        logger.info(f"Request received for scanned local song (uls): {song_id}")
        try:
            conn = get_pg_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Query the 'uls_songs' table and join to get the artist name
                sql_query = """
                    SELECT s.file_path, s.title, a.name as artist
                    FROM uls_songs s
                    LEFT JOIN artists a ON s.artist_id = a.id
                    WHERE s.id = %s AND s.is_deleted = FALSE;
                """
                cur.execute(sql_query, (song_id,))
                local_song_data = cur.fetchone()

                # Check if the song exists in the DB and the file is on the disk
                if local_song_data and local_song_data.get('file_path') and os.path.exists(local_song_data['file_path']):
                    logger.info(f"✅ Found valid path for '{song_id}'. Preparing to send file.")
                    return send_downloadable_file(local_song_data['file_path'], local_song_data)
                else:
                    logger.error(f"❌ Scanned local song '{song_id}' requested but not found in DB or its path is invalid.")
                    return jsonify({"error": "Local file not found on server."}), 404
        except Exception as e:
            logger.error(f"Error processing scanned local song '{song_id}': {e}", exc_info=True)
            return jsonify({"error": "Server error during local song download preparation."}), 500
        finally:
            if conn and not conn.closed:
                conn.close()

    # --- Handle YouTube songs (quality-aware) ---
    else:
        try:
            # 1. Get the user's desired quality setting.
            quality = util.get_stream_quality(user_id_session)
            if not quality:
                logger.warning(f"Could not determine stream quality for user {user_id_session}. Defaulting to lossless.")
                quality = 'lossless'

            # 2. Determine the expected file path based on song ID and quality.
            expected_filepath = util.get_song_filepath(song_id, quality)
            logger.info(f"Checking for song '{song_id}' with quality '{quality}' at path: {expected_filepath}")

            # 3. Check if the file for the required quality already exists.
            if os.path.exists(expected_filepath):
                logger.info(f"Cache HIT: Found existing file for song '{song_id}' with quality '{quality}'.")
                # Fetch metadata to create a user-friendly filename for the download.
                song_meta = util.get_media_info_util(song_id)
                if not song_meta:
                    song_meta = {'title': song_id, 'artist': 'Unknown'}
                    logger.warning(f"Could not fetch metadata for {song_id}, using default names.")
                
                return send_downloadable_file(expected_filepath, song_meta)

            # 4. If the file doesn't exist, start the background download task.
            else:
                logger.info(f"Cache MISS for YT song '{song_id}' (quality: {quality}). Initiating background download.")
                task = download_youtube_song_task.delay(song_id, user_id_session)
                # Respond immediately to the client that the task is processing.
                return jsonify({
                    'status': 'processing',
                    'task_id': task.id,
                    # Note: If this app is run behind a blueprint, the endpoint name might need to be 'blueprint_name.task_status'
                    'check_status_url': url_for('task_status', task_id=task.id, _external=True)
                }), 202

        except Exception as e:
            logger.error(f"Download route error for YouTube song '{song_id}': {e}", exc_info=True)
            return jsonify({"error": "An error occurred during download preparation."}), 500

@bp.route("/download-server/api/status/<task_id>")
def task_status(task_id):
    """
    Checks the status of a download task. This function will now work correctly.
    """
    task = download_youtube_song_task.AsyncResult(task_id)
    response_data = {'state': task.state, 'status': ''}

    if task.state == 'PENDING':
        response_data['status'] = 'Pending...'
    elif task.state == 'PROGRESS':
        response_data['status'] = task.info.get('status', 'In progress...')
    elif task.state == 'SUCCESS':
        response_data['status'] = 'Download successful!'
        # This part will no longer cause an error because the task result now contains the required info.
        response_data['download_url'] = url_for('api_download', song_id=task.info.get('song_id'), user_id_session=task.info.get('user_id'), _external=True)
        response_data['result'] = task.info
    elif task.state == 'FAILURE':
        response_data['status'] = str(task.info)  # Contains the exception
    
    return jsonify(response_data)


def send_downloadable_file(filepath, song_meta):
    """
    Helper function to send a file as a download attachment with the correct mimetype and filename.
    """
    try:
        if not os.path.exists(filepath):
            logger.error(f"File to be sent does not exist at path: {filepath}")
            return jsonify({"error": "Requested file is not available on the server."}), 404

        # Get the file extension to determine mimetype
        _, ext = os.path.splitext(filepath)
        ext = ext.lower()

        mimetypes = {
            '.flac': 'audio/flac',
            '.opus': 'audio/opus',
            '.ogg': 'audio/ogg',
            '.m4a': 'audio/mp4',
            '.wav': 'audio/wav'
        }
        mimetype = mimetypes.get(ext, 'application/octet-stream')

        # Create a user-friendly download filename
        title = song_meta.get('title') or "Unknown Title"
        artist = song_meta.get('artist') or "Unknown Artist"
        
        # Sanitize and create the final filename
        download_filename = f"{util.sanitize_filename(f'{artist} - {title}')}{ext}"

        logger.info(f"Sending file '{filepath}' as attachment '{download_filename}' with mimetype '{mimetype}'.")
        return send_file(filepath, as_attachment=True, download_name=download_filename, mimetype=mimetype)
    
    except Exception as e:
        logger.error(f"Error in send_downloadable_file for path {filepath}: {e}", exc_info=True)
        return jsonify({"error": "Server error while sending file."}), 500


# --- CRITICAL DEPLOYMENT NOTE ---
# The following line is suitable for simple testing but not for production.
# In a production environment, the Celery worker should be managed by a process supervisor like systemd or Supervisor.
# Running it with subprocess.Popen from the Flask app can lead to orphaned processes and is not a reliable way to manage services.
try:
    subprocess.Popen("celery -A celery_app.celery worker --loglevel=info" , shell=True)
except Exception as e:
    logger.error(f"Could not start celery worker automatically: {e}")
    logger.warning("Please ensure the Celery worker is running in a separate terminal for downloads to work.")
# Example command to run manually: celery -A celery_app.celery worker --loglevel=info

if __name__ == "__main__":
    # For development, you would run the Flask app and the Celery worker in separate terminals.
    # Do not run the celery worker using subprocess in a production environment.
    bp.run(host="localhost", port=2301)