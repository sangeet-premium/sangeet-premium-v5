from celery_app import celery
from database.database import get_pg_connection
from utils import util
import os
import psycopg2
import logging

logger = logging.getLogger(__name__)

@celery.task(bind=True)
def download_youtube_song_task(self, song_id, user_id_session):
    """
    Celery task to download a song from YouTube.
    This function now contains the logic that was likely in util.download_flac_pg.
    """
    conn = None
    try:
        # Update task state to 'PROGRESS'
        self.update_state(state='PROGRESS', meta={'status': 'Downloading...'})

        # This is where your actual YouTube download logic goes.
        flac_path = util.download_flac_pg(song_id, user_id_session)

        if not flac_path or not os.path.exists(flac_path):
            raise ValueError("File not downloaded or not found at the given path.")

        # --- FIX: The return dictionary MUST include the IDs for the next step ---
        return {
            'status': 'SUCCESS',
            'path': flac_path,
            'song_id': song_id,          # Added this line
            'user_id': user_id_session   # Added this line
        }

    except Exception as e:
        logger.error(f"Celery task failed for song {song_id}: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'status': str(e)})
        raise

    finally:
        if conn and not conn.closed:
            conn.close()