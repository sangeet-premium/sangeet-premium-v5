# BOTTLE IMPORTS: Replaced Flask imports with Bottle's
from bottle import (Bottle, static_file, request, response) 
from database.database import get_pg_connection
import psycopg2.extras 
from utils import util
from functools import wraps

import os
import subprocess

# Import the Celery app and the task (No change needed here)
from celery_app import celery
from tasks import download_youtube_song_task
from logger.log import setup_logger as log

# BOTTLE APP: Use Bottle() instead of Flask()
bp = Bottle()
logger = log(__name__)

# BOTTLE CORS: Use a hook for CORS headers instead of Flask-CORS extension
@bp.hook('after_request')
def enable_cors():
    """Add headers to enable CORS."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'

# BOTTLE ROUTE: Use app.route and add a 'name' for URL generation
@bp.route("/download-server/api/download/<song_id>/<user_id_session>", name='api_download')
def api_download(song_id, user_id_session):
    """
    Handles all song requests by checking for the correct file based on quality settings first.
    If the file doesn't exist, it initiates a download.
    This works for both local files (served as-is) and YouTube downloads (quality-aware).
    """
    conn = None
    if song_id.startswith("local-"):
        try:
            conn = get_pg_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM local_songs WHERE id = %s", (song_id,))
                local_song = cur.fetchone()
                if local_song and local_song.get('path') and os.path.exists(local_song['path']):
                    logger.info(f"Serving local library song: {song_id}")
                    return send_downloadable_file(local_song['path'], local_song)
                else:
                    logger.error(f"Local song '{song_id}' requested but not found in DB or path is invalid.")
                    # BOTTLE JSON: Set status and return dict
                    response.status = 404
                    return {"error": "Local file not found"}
        except Exception as e:
            logger.error(f"Error processing local song '{song_id}': {e}", exc_info=True)
            # BOTTLE JSON: Set status and return dict
            response.status = 500
            return {"error": "Server error during local song download."}
        finally:
            if conn and not conn.closed:
                conn.close()
    elif song_id.startswith("uls-"):
        logger.info(f"Request received for scanned local song (uls): {song_id}")
        try:
            conn = get_pg_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                sql_query = """
                    SELECT s.file_path, s.title, a.name as artist
                    FROM uls_songs s
                    LEFT JOIN artists a ON s.artist_id = a.id
                    WHERE s.id = %s AND s.is_deleted = FALSE;
                """
                cur.execute(sql_query, (song_id,))
                local_song_data = cur.fetchone()
                if local_song_data and local_song_data.get('file_path') and os.path.exists(local_song_data['file_path']):
                    logger.info(f"✅ Found valid path for '{song_id}'. Preparing to send file.")
                    return send_downloadable_file(local_song_data['file_path'], local_song_data)
                else:
                    logger.error(f"❌ Scanned local song '{song_id}' requested but not found in DB or its path is invalid.")
                    # BOTTLE JSON: Set status and return dict
                    response.status = 404
                    return {"error": "Local file not found on server."}
        except Exception as e:
            logger.error(f"Error processing scanned local song '{song_id}': {e}", exc_info=True)
            # BOTTLE JSON: Set status and return dict
            response.status = 500
            return {"error": "Server error during local song download preparation."}
        finally:
            if conn and not conn.closed:
                conn.close()
    else:
        try:
            quality = util.get_stream_quality(user_id_session)
            if not quality:
                logger.warning(f"Could not determine stream quality for user {user_id_session}. Defaulting to lossless.")
                quality = 'lossless'
            
            expected_filepath = util.get_song_filepath(song_id, quality)
            logger.info(f"Checking for song '{song_id}' with quality '{quality}' at path: {expected_filepath}")

            if os.path.exists(expected_filepath):
                logger.info(f"Cache HIT: Found existing file for song '{song_id}' with quality '{quality}'.")
                song_meta = util.get_media_info_util(song_id)
                if not song_meta:
                    song_meta = {'title': song_id, 'artist': 'Unknown'}
                    logger.warning(f"Could not fetch metadata for {song_id}, using default names.")
                
                return send_downloadable_file(expected_filepath, song_meta)
            else:
                logger.info(f"Cache MISS for YT song '{song_id}' (quality: {quality}). Initiating background download.")
                task = download_youtube_song_task.delay(song_id, user_id_session)
                
                # BOTTLE URL_FOR: Use app.get_url and build the full URL manually
                base_url = f"{request.urlparts.scheme}://{request.urlparts.netloc}"
                check_url = bp.get_url('task_status', task_id=task.id)

                # BOTTLE JSON: Set status and return dict
                response.status = 202
                return {
                    'status': 'processing',
                    'task_id': task.id,
                    'check_status_url': f"{base_url}{check_url}"
                }
        except Exception as e:
            logger.error(f"Download route error for YouTube song '{song_id}': {e}", exc_info=True)
            # BOTTLE JSON: Set status and return dict
            response.status = 500
            return {"error": "An error occurred during download preparation."}

# BOTTLE ROUTE: Use app.route and add a 'name'
@bp.route("/download-server/api/status/<task_id>", name='task_status')
def task_status(task_id):
    """
    Checks the status of a download task.
    """
    task = download_youtube_song_task.AsyncResult(task_id)
    response_data = {'state': task.state, 'status': ''}

    if task.state == 'PENDING':
        response_data['status'] = 'Pending...'
    elif task.state == 'PROGRESS':
        response_data['status'] = task.info.get('status', 'In progress...')
    elif task.state == 'SUCCESS':
        response_data['status'] = 'Download successful!'
        
        # BOTTLE URL_FOR: Use app.get_url and build the full URL manually
        base_url = f"{request.urlparts.scheme}://{request.urlparts.netloc}"
        download_path = bp.get_url('api_download', song_id=task.info.get('song_id'), user_id_session=task.info.get('user_id'))
        
        response_data['download_url'] = f"{base_url}{download_path}"
        response_data['result'] = task.info
    elif task.state == 'FAILURE':
        response_data['status'] = str(task.info)  
    
    return response_data # Bottle handles dict -> JSON automatically

# BOTTLE SEND_FILE: The helper function is adapted to use static_file
def send_downloadable_file(filepath, song_meta):
    """
    Helper function to send a file as a download attachment using Bottle's static_file.
    """
    try:
        if not os.path.exists(filepath):
            logger.error(f"File to be sent does not exist at path: {filepath}")
            response.status = 404
            return {"error": "Requested file is not available on the server."}

        # BOTTLE STATIC_FILE requires a root directory and a filename
        root_dir = os.path.dirname(filepath)
        filename = os.path.basename(filepath)

        _, ext = os.path.splitext(filepath)
        ext = ext.lower()

        # mimetypes = {
        #     '.flac': 'audio/flac', '.opus': 'audio/opus', '.ogg': 'audio/ogg',
        #     '.m4a': 'audio/mp4', '.wav': 'audio/wav'
        # }
        # mimetype = mimetypes.get(ext, 'application/octet-stream')

        title = song_meta.get('title') or "Unknown Title"
        artist = song_meta.get('artist') or "Unknown Artist"
        
        download_filename = f"{util.sanitize_filename(f'{artist} - {title}')}{ext}"

        logger.info(f"Sending file '{filename}' from root '{root_dir}' as attachment '{download_filename}'.")
        # The 'download' parameter triggers the download dialog.
        return static_file(filename, root=root_dir, download=download_filename)
    
    except Exception as e:
        logger.error(f"Error in send_downloadable_file for path {filepath}: {e}", exc_info=True)
        response.status = 500
        return {"error": "Server error while sending file."}

# --- Celery and Main Execution Block ---
# This part of the logic is framework-agnostic and remains the same.
try:
    subprocess.Popen("celery -A celery_app.celery worker --loglevel=info" , shell=True)
except Exception as e:
    logger.error(f"Could not start celery worker automatically: {e}")
    logger.warning("Please ensure the Celery worker is running in a separate terminal for downloads to work.")

if __name__ == "__main__":
    # BOTTLE RUN: Use app.run() to start the server
    bp.run(host="localhost", port=2301, debug=True)