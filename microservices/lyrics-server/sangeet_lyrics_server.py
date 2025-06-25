import os
import syncedlyrics
from flask_cors import CORS
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import logging
import re
import traceback
import psycopg2 # Import psycopg2
import time # Import time for retries

# --- Configuration & Initialization ---
if not logging.getLogger().hasHandlers(): # Ensure basicConfig is called only once
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "config.conf")
if not os.path.exists(dotenv_path):
    logger.warning(f"Warning: config.conf not found at {dotenv_path}. Trying current working directory.")
    dotenv_path = os.path.join(os.getcwd(), "configs", "config.conf")

load_dotenv(dotenv_path=dotenv_path)
logger.info(f"Loading .env from {dotenv_path}")

# --- Database Configuration (using psycopg2 and defaults) ---
POSTGRES_USER = os.getenv("POSTGRES_USER", "your_postgres_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "your_postgres_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres_main_database_server")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "sangeet-ui")

# --- Retry Configuration ---
DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", 5))
DB_CONNECT_RETRY_DELAY = int(os.getenv("DB_CONNECT_RETRY_DELAY", 3)) # seconds

if not all([POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB]):
    logger.error("CRITICAL: Database credentials not fully loaded. Check config.conf or defaults.")

app = Flask(__name__)
CORS(app)

# --- Database Connection Function (psycopg2 with retry) ---
def get_pg_connection():
    """Establishes a connection to the PostgreSQL database with retry logic."""
    conn = None
    last_exception = None
    for attempt in range(DB_CONNECT_RETRIES):
        try:
            conn = psycopg2.connect(
                dbname=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                connect_timeout=5 # Add a connection timeout
            )
            logger.info(f"Successfully connected to PostgreSQL database '{POSTGRES_DB}' at {POSTGRES_HOST}:{POSTGRES_PORT} on attempt {attempt + 1}")
            return conn
        except psycopg2.Error as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} to connect to database failed: {e}")
            if attempt < DB_CONNECT_RETRIES - 1:
                logger.info(f"Retrying in {DB_CONNECT_RETRY_DELAY} seconds...")
                time.sleep(DB_CONNECT_RETRY_DELAY)
            else:
                logger.error(f"All {DB_CONNECT_RETRIES} attempts to connect to the database failed.")
                break # Exit loop after all retries
    if last_exception: # If loop finished due to retries exhausted
        raise last_exception # Raise the last encountered exception
    return None # Should not be reached if raise happens, but as a fallback

# --- Database Table Creation (psycopg2) ---
def create_lyrics_table_if_not_exists():
    """Creates the 'lyrics' table in the database if it doesn't already exist."""
    conn = None
    try:
        conn = get_pg_connection() # This will now retry
        if conn is None: # Check if connection failed after retries
            logger.error("Cannot create lyrics table, database connection failed after all retries.")
            return # Exit if no connection

        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lyrics (
                    song_id VARCHAR(255) PRIMARY KEY,
                    plain_lyrics TEXT,
                    synced_lyrics_lrc TEXT,
                    provider VARCHAR(100)
                );
            """)
            conn.commit()
        # If the above executes without error, it means the table was created or already existed.
        logger.info("Table 'lyrics' checked or created successfully.")

    except psycopg2.errors.UniqueViolation as uv_error: # type: ignore
        # Check if the error is specifically about the pg_type constraint for the 'lyrics' type
        # The pgcode for unique_violation is '23505'
        if hasattr(uv_error, 'pgcode') and uv_error.pgcode == '23505' and \
           isinstance(uv_error.pgerror, str) and "pg_type_typname_nsp_index" in uv_error.pgerror.lower() and \
           "(lyrics, 2200)" in uv_error.pgerror.lower(): # Check for (lyrics, 2200) for more specificity
            logger.warning(
                f"Table 'lyrics' creation: Encountered unique violation for pg_type (likely concurrent worker setup). "
                f"Assuming table exists or will be created by another process. Details: {uv_error.pgerror}"
            )
            if conn:
                try:
                    conn.rollback() # Rollback the current transaction as it failed
                except psycopg2.Error as rb_err: # type: ignore
                    logger.error(f"Error during rollback after pg_type UniqueViolation: {rb_err}")
        else:
            # If it's a different unique violation, it's unexpected with IF NOT EXISTS
            # or if the details don't match the specific pg_type issue.
            logger.error(f"Error creating/checking 'lyrics' table (Unexpected UniqueViolation): {uv_error}", exc_info=True)
            if conn:
                try:
                    conn.rollback()
                except psycopg2.Error as rb_err: # type: ignore
                    logger.error(f"Error during rollback for other UniqueViolation: {rb_err}")
            raise # Re-raise other unique violations that are not the pg_type one
    except psycopg2.Error as e: # Catch other psycopg2 errors
        logger.error(f"Error creating/checking 'lyrics' table: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except psycopg2.Error as rb_err: # type: ignore
                 logger.error(f"Error during rollback for general psycopg2.Error: {rb_err}")
        raise # Re-raise other database errors
    except Exception as e_main: # Catch any other unexpected errors
        logger.error(f"Unexpected error during table creation: {e_main}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except psycopg2.Error as rb_err: # type: ignore
                 logger.error(f"Error during rollback for general Exception: {rb_err}")
        raise
    finally:
        if conn:
            conn.close()
# --- Lyrics Data Class (Simple class, not an ORM model) ---
class LyricsData:
    def __init__(self, song_id, plain_lyrics, synced_lyrics_lrc, provider):
        self.song_id = song_id
        self.plain_lyrics = plain_lyrics
        self.synced_lyrics_lrc = synced_lyrics_lrc
        self.provider = provider

    def to_dict(self):
        return {
            "plain": self.plain_lyrics,
            "synced": self.synced_lyrics_lrc,
            "provider": self.provider
        }

# --- Helper Function to Check LRC Format ---
def is_lrc_format(text):
    if not isinstance(text, str):
        logger.debug(f"[is_lrc_format] Input is not a string, type: {type(text)}")
        return False
    lrc_line_pattern = re.compile(r"^\s*\[\d{2}:\d{2}[.:]\d{2,3}\]")
    lines = text.splitlines()
    if not lines:
        logger.debug(f"[is_lrc_format] Input string has no lines.")
        return False
    lrc_line_count = sum(1 for line in lines if lrc_line_pattern.match(line))
    is_lrc = lrc_line_count > 0 and (lrc_line_count / len(lines) > 0.15 or lrc_line_count >= 2)
    logger.debug(f"[is_lrc_format] Text analyzed. LRC-like lines: {lrc_line_count}/{len(lines)}. Determined LRC: {is_lrc}")
    return is_lrc

# --- Lyrics Service Logic (using psycopg2) ---
# def search_and_save_lyrics_from_api(song_id, song_title, song_artist):
#     search_term = f"{song_title} {song_artist}"
#     logger.info(f"[API Search] For song_id: {song_id}, search_term: '{search_term}'")

#     lrc_lyrics_text = None
#     plain_lyrics_text = None
#     provider_name = "syncedlyrics_provider"
#     conn = None

#     try:
#         logger.info(f"[API Search] Calling syncedlyrics.search for '{search_term}' (save_path=False, providers=[])")
#         raw_lyrics = syncedlyrics.search(search_term, save_path=False, providers=[])

#         if raw_lyrics and isinstance(raw_lyrics, str) and raw_lyrics.strip():
#             logger.info(f"[API Search] Syncedlyrics returned for '{search_term}'. Type: {type(raw_lyrics)}, Length: {len(raw_lyrics)}")
#             if is_lrc_format(raw_lyrics):
#                 lrc_lyrics_text = raw_lyrics
#                 logger.info(f"[API Search] Detected as LRC for '{search_term}'.")
#             else:
#                 plain_lyrics_text = raw_lyrics
#                 logger.info(f"[API Search] Detected as PLAIN for '{search_term}'.")
#         elif not raw_lyrics or (isinstance(raw_lyrics, str) and not raw_lyrics.strip()):
#             logger.warning(f"[API Search] No content returned by syncedlyrics.search for '{search_term}'.")
#             return None
#         else:
#             logger.warning(f"[API Search] Unexpected format from syncedlyrics for '{search_term}': {type(raw_lyrics)}.")
#             return None

#         if not lrc_lyrics_text and not plain_lyrics_text:
#             logger.warning(f"[API Search] After processing, both LRC and Plain lyrics are empty for '{search_term}'.")
#             return None

#         logger.info(f"[DB Save] Attempting to store API lyrics for {song_id}.")
#         conn = get_pg_connection()
#         if conn is None:
#             logger.error(f"[DB Save] Failed to get DB connection for {song_id} after retries.")
#             return None

#         with conn.cursor() as cur:
#             cur.execute("""
#                 INSERT INTO lyrics (song_id, plain_lyrics, synced_lyrics_lrc, provider)
#                 VALUES (%s, %s, %s, %s)
#                 ON CONFLICT (song_id) DO UPDATE SET
#                     plain_lyrics = EXCLUDED.plain_lyrics,
#                     synced_lyrics_lrc = EXCLUDED.synced_lyrics_lrc,
#                     provider = EXCLUDED.provider;
#             """, (song_id, plain_lyrics_text, lrc_lyrics_text, provider_name))
#             conn.commit()
#         logger.info(f"[DB Save] Successfully saved/updated API lyrics for {song_id} to DB.")
#         return LyricsData(song_id, plain_lyrics_text, lrc_lyrics_text, provider_name)

#     except TypeError as te:
#         logger.error(f"[API Search/DB TYPE_ERROR] For '{search_term}': {te}\n{traceback.format_exc()}")
#         if conn: conn.rollback()
#         if "unexpected keyword argument 'providers'" in str(te) or "unexpected keyword argument" in str(te):
#             logger.warning(f"[API Search] Retrying syncedlyrics.search without 'providers' argument for '{search_term}'")
#             try:
#                 raw_lyrics_retry = syncedlyrics.search(search_term, save_path=False)
#                 if raw_lyrics_retry and isinstance(raw_lyrics_retry, str) and raw_lyrics_retry.strip():
#                     if is_lrc_format(raw_lyrics_retry): lrc_lyrics_text = raw_lyrics_retry
#                     else: plain_lyrics_text = raw_lyrics_retry

#                     if lrc_lyrics_text or plain_lyrics_text:
#                         if not conn or conn.closed:
#                            conn = get_pg_connection()
#                         if conn is None:
#                             logger.error(f"[DB Save Retry] Failed to get DB connection for {song_id} after retries.")
#                             return None
#                         with conn.cursor() as cur_retry:
#                             cur_retry.execute("""
#                                 INSERT INTO lyrics (song_id, plain_lyrics, synced_lyrics_lrc, provider)
#                                 VALUES (%s, %s, %s, %s)
#                                 ON CONFLICT (song_id) DO UPDATE SET
#                                     plain_lyrics = EXCLUDED.plain_lyrics,
#                                     synced_lyrics_lrc = EXCLUDED.synced_lyrics_lrc,
#                                     provider = EXCLUDED.provider;
#                             """, (song_id, plain_lyrics_text, lrc_lyrics_text, "syncedlyrics_retry_no_providers"))
#                             conn.commit()
#                         logger.info(f"[DB Save Retry] Successfully saved API lyrics for {song_id} to DB after retry.")
#                         return LyricsData(song_id, plain_lyrics_text, lrc_lyrics_text, "syncedlyrics_retry_no_providers")
#                     else:
#                         logger.warning(f"[API Search Retry] Lyrics processed but both empty after retry for '{search_term}'.")
#                         return None
#                 else:
#                     logger.warning(f"[API Search Retry] No content or wrong type after retry for '{search_term}'.")
#                     return None
#             except Exception as retry_e:
#                 if conn: conn.rollback()
#                 logger.error(f"[API Search/DB EXCEPTION RETRY] For '{search_term}': {retry_e}\n{traceback.format_exc()}")
#                 return None
#         return None
#     except psycopg2.Error as db_err:
#         if conn: conn.rollback()
#         logger.error(f"[DB psycopg2.Error] For '{search_term}': {db_err}\n{traceback.format_exc()}")
#         return None
#     except Exception as e:
#         if conn: conn.rollback()
#         logger.error(f"[API Search/DB EXCEPTION] For '{search_term}': {e}\n{traceback.format_exc()}")
#         return None
#     finally:
#         if conn:
#             conn.close()



def search_and_save_lyrics_from_api(song_id, song_title, song_artist):
    search_term = f"{song_title} {song_artist}"
    logger.info(f"[API Search] For song_id: {song_id}, search_term: '{search_term}'")

    lrc_lyrics_text = None
    plain_lyrics_text = None
    raw_lyrics = None  # To store result from syncedlyrics
    final_provider_name = "unknown_provider"  # To store the name of the provider that succeeded
    conn = None

    # Define the order of providers to try.
    # Ensure these names are valid for your version of syncedlyrics.
    # Common examples: "Musixmatch", "Lrclib", "Megalobiz", "NetEase", "Genius"
    # Adjust this list as per available and desired providers.
    ordered_providers = ["Musixmatch", "Lrclib", "Megalobiz", "NetEase", "Genius"]

    try:
        # 1. Try providers from the ordered list
        for provider_candidate in ordered_providers:
            logger.info(f"[API Search] Trying provider: {provider_candidate} for '{search_term}'")
            try:
                current_lyrics = syncedlyrics.search(
                    search_term,
                    save_path=False,
                    providers=[provider_candidate]
                )

                if current_lyrics and isinstance(current_lyrics, str) and current_lyrics.strip():
                    raw_lyrics = current_lyrics
                    final_provider_name = provider_candidate
                    logger.info(f"[API Search] Lyrics found via provider: {final_provider_name} for '{search_term}'. Length: {len(raw_lyrics)}")
                    break  # Lyrics found, exit loop
                else:
                    logger.info(f"[API Search] No lyrics found via provider: {provider_candidate} for '{search_term}'.")
            except Exception as e_provider:
                logger.warning(f"[API Search] Error searching with provider {provider_candidate} for '{search_term}': {e_provider}")
                # Optionally, add more detailed error logging here: logger.debug(traceback.format_exc())
                continue  # Try next provider

        # 2. If no lyrics found from the ordered list, try a generic fallback
        if not raw_lyrics:
            logger.info(f"[API Search Fallback] No lyrics from provider list. Trying generic search for '{search_term}'")
            try:
                raw_lyrics_fallback = syncedlyrics.search(
                    search_term,
                    save_path=False,
                    allow_plain_lyrics=True # Default providers, allow plain
                )
                if raw_lyrics_fallback and isinstance(raw_lyrics_fallback, str) and raw_lyrics_fallback.strip():
                    raw_lyrics = raw_lyrics_fallback
                    final_provider_name = "syncedlyrics_generic_fallback"
                    logger.info(f"[API Search Fallback] Lyrics found via generic fallback for '{search_term}'. Length: {len(raw_lyrics)}")
                else:
                    logger.warning(f"[API Search Fallback] Generic fallback also yielded no lyrics for '{search_term}'.")
            except Exception as fallback_e:
                logger.error(f"[API Search Fallback] Error during generic fallback search for '{search_term}': {fallback_e}")
                # Optionally, add more detailed error logging here

        # 3. Process the lyrics if any were found (either from loop or fallback)
        if raw_lyrics:
            logger.info(f"[API Processing] Lyrics obtained via '{final_provider_name}'. Processing content...")
            if is_lrc_format(raw_lyrics):
                lrc_lyrics_text = raw_lyrics
                logger.info(f"[API Processing] Detected as LRC for '{search_term}' from '{final_provider_name}'.")
            else:
                plain_lyrics_text = raw_lyrics
                logger.info(f"[API Processing] Detected as PLAIN for '{search_term}' from '{final_provider_name}'.")
        else:
            logger.warning(f"[API Result] After all attempts (specific providers and fallback), no lyrics found for '{search_term}'.")
            return None # No usable lyrics to save

        # Ensure we have something to save
        if not lrc_lyrics_text and not plain_lyrics_text:
            logger.warning(f"[API Result] Lyrics processed but both LRC and Plain are empty for '{search_term}'.")
            return None

        # 4. Database Saving Logic
        logger.info(f"[DB Save] Attempting to store API lyrics for {song_id} from provider '{final_provider_name}'.")
        conn = get_pg_connection()
        if conn is None:
            logger.error(f"[DB Save] Failed to get DB connection for {song_id} after retries. Lyrics from '{final_provider_name}' not saved.")
            # Depending on requirements, you might still want to return the lyrics even if DB save fails.
            # For now, returning None if DB connection fails before saving.
            return None # Or return LyricsData(...) if you want to send lyrics to client even if not saved

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lyrics (song_id, plain_lyrics, synced_lyrics_lrc, provider)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (song_id) DO UPDATE SET
                    plain_lyrics = EXCLUDED.plain_lyrics,
                    synced_lyrics_lrc = EXCLUDED.synced_lyrics_lrc,
                    provider = EXCLUDED.provider;
            """, (song_id, plain_lyrics_text, lrc_lyrics_text, final_provider_name)) # Use final_provider_name
            conn.commit()
        logger.info(f"[DB Save] Successfully saved/updated API lyrics for {song_id} (from '{final_provider_name}') to DB.")
        return LyricsData(song_id, plain_lyrics_text, lrc_lyrics_text, final_provider_name) # Use final_provider_name

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"[DB psycopg2.Error] For '{search_term}', provider '{final_provider_name}': {db_err}\n{traceback.format_exc()}")
        return None
    except Exception as e: # General catch-all for unexpected issues in this function
        if conn: conn.rollback()
        logger.error(f"[API Search/Save EXCEPTION] For '{search_term}', provider '{final_provider_name}': {e}\n{traceback.format_exc()}")
        return None
    finally:
        if conn:
            conn.close()


# --- API Endpoint (using psycopg2) ---
@app.route('/lyrics-server/lyrics', methods=['GET'])
def get_lyrics_endpoint():
    song_id = request.args.get('song_id')
    song_title = request.args.get('title')
    song_artist = request.args.get('artist')
    conn = None

    required_params = {'song_id': song_id, 'title': song_title, 'artist': song_artist}
    missing_params = [k for k, v in required_params.items() if not v]

    if missing_params:
        message = f"Missing required query parameters: {', '.join(missing_params)}"
        logger.warning(f"[ENDPOINT] {message}")
        return jsonify({"success": False, "message": message}), 400

    logger.info(f"--- Request IN --- ID: '{song_id}', Title: '{song_title}', Artist: '{song_artist}' ---")

    try:
        conn = get_pg_connection()
        if conn is None:
            logger.error(f"[ENDPOINT] Failed to get DB connection for song_id '{song_id}' after retries.")
            return jsonify({
                "success": False,
                "message": "Database connection error after multiple retries.",
                "data": {"plain": None, "synced": None, "provider": None}
            }), 500

        with conn.cursor() as cur:
            cur.execute("SELECT song_id, plain_lyrics, synced_lyrics_lrc, provider FROM lyrics WHERE song_id = %s", (song_id,))
            db_row = cur.fetchone()

        if db_row:
            db_lyrics_entry = LyricsData(song_id=db_row[0], plain_lyrics=db_row[1], synced_lyrics_lrc=db_row[2], provider=db_row[3])
            logger.info(f"[ENDPOINT] Lyrics for '{song_id}' found in DB.")
            return jsonify({
                "success": True,
                "data": db_lyrics_entry.to_dict(),
                "source": "database"
            }), 200

        logger.info(f"[ENDPOINT] Lyrics for '{song_id}' not in DB. Calling API search & store.")
        newly_fetched_lyrics_entry = search_and_save_lyrics_from_api(song_id, song_title, song_artist)

        if newly_fetched_lyrics_entry:
            logger.info(f"[ENDPOINT] API fetch successful for '{song_id}'. Returning lyrics.")
            return jsonify({
                "success": True,
                "data": newly_fetched_lyrics_entry.to_dict(),
                "source": "api"
            }), 200
        else:
            logger.warning(f"[ENDPOINT] API search did not yield saveable lyrics for '{song_id}'. Returning 'Lyrics not found.' (404)")
            return jsonify({
                "success": False,
                "message": "Lyrics not found.",
                "data": {"plain": None, "synced": None, "provider": None}
            }), 404

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"[ENDPOINT psycopg2.Error] For song_id '{song_id}': {db_err}\n{traceback.format_exc()}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Database error fetching lyrics: {str(db_err)}",
            "data": {"plain": None, "synced": None, "provider": None}
        }), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[ENDPOINT CRITICAL] For song_id '{song_id}': {e}\n{traceback.format_exc()}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error fetching lyrics: {str(e)}",
            "data": {"plain": None, "synced": None, "provider": None}
        }), 500
    finally:
        if conn:
            conn.close()

def main_setup():
    logger.info("Initializing database: Creating 'lyrics' table if it doesn't exist...")
    try:
        create_lyrics_table_if_not_exists()
        # The success log is now inside create_lyrics_table_if_not_exists
    except Exception as e:
        logger.error(f"CRITICAL: Error during main_setup (table creation for lyrics): {e}\n{traceback.format_exc()}", exc_info=True)
        # Consider if you want to exit the application if DB setup fails
        # For now, it logs and the Flask app might still try to run, but DB operations will fail.
        # raise SystemExit(f"Failed to initialize database: {e}") # Option to exit

main_setup()

if __name__ == "__main__":
    if not all([POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB]):
        logger.error("CRITICAL: Server cannot start - missing database credentials.")
    else:
        logger.info(f"Starting Sangeet Lyrics Flask server on http://0.0.0.0:2302")
        app.run(host="0.0.0.0", port=2302, threaded=True)
