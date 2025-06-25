# database.py
import psycopg2
import os
import logging
from dotenv import load_dotenv

# --- Logging Setup ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.getcwd(), "configs", "ui" , "config.conf") # Adjust path as needed
load_dotenv(dotenv_path=dotenv_path)

POSTGRES_USER = os.getenv("POSTGRES_USER", "your_postgres_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "your_postgres_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "sangeet_main_db")

# --- Database Connection Function ---
def get_pg_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        raise

# --- Schema Initialization Function ---
def init_postgres_db():
    """Initializes all tables in the PostgreSQL database."""
    conn = None
    try:
        conn = get_pg_connection()
        c = conn.cursor()

        logger.info(f"Initializing PostgreSQL database '{POSTGRES_DB}'...")

        # User Authentication & Session Tables
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                totp_secret TEXT,
                twofa_method TEXT DEFAULT 'none', -- e.g., 'none', 'totp', 'email'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Table 'users' created or already exists.")

        c.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        logger.info("Table 'active_sessions' created or already exists.")

        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_otps (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                otp TEXT NOT NULL,
                purpose TEXT NOT NULL, -- e.g., 'registration', 'password_reset', 'login'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        logger.info("Table 'pending_otps' created or already exists.")

        # Local Songs (replaces Redis set and hashes for local music)
        c.execute("""
            CREATE TABLE IF NOT EXISTS local_songs (
                id TEXT PRIMARY KEY, -- Typically "local-filename" or similar unique ID
                title TEXT,
                artist TEXT,
                album TEXT,
                path TEXT UNIQUE NOT NULL, -- File path on disk
                duration INTEGER, -- seconds
                genre TEXT -- Added genre column
            )
        """)
        logger.info("Table 'local_songs' created or already exists.")

        # User Downloads (migrated from SQLite)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_downloads (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                video_id TEXT NOT NULL,
                title TEXT,
                artist TEXT,
                album TEXT,
                path TEXT NOT NULL,
                downloaded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, video_id) -- Add this line
            );
        """)
        logger.info("Table 'user_downloads' created or already exists.")

        # Listening History (detailed, from SQLite's listening_history)
        c.execute("""
            CREATE TABLE IF NOT EXISTS listening_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, -- Keep history if user deleted
                song_id TEXT NOT NULL,
                title TEXT,
                artist TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                duration INTEGER, -- Total duration of the song in seconds
                listened_duration INTEGER, -- Actual time listened in seconds
                completion_rate FLOAT, -- listened_duration / duration
                session_id TEXT, -- To group listens within a play session
                listen_type TEXT CHECK(listen_type IN ('full', 'partial', 'skip')) DEFAULT 'partial'
            )
        """)
        logger.info("Table 'listening_history' created or already exists.")
        
        # User Play History (simpler, for 'next/previous' queue, from Redis list user_history:{user_id})
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_play_queue_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                song_id TEXT NOT NULL,
                session_id TEXT, -- Playback session identifier
                sequence_number INTEGER, -- Order of song in the session
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                title TEXT, -- Denormalized for easier queue display
                artist TEXT -- Denormalized
            )
        """)
        logger.info("Table 'user_play_queue_history' created or already exists.")


        # User Statistics (migrated from SQLite user_stats & Redis user_stats:{user_id})
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_statistics (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                total_plays INTEGER DEFAULT 0,
                total_listened_time INTEGER DEFAULT 0, -- in seconds
                favorite_song_id TEXT,
                favorite_artist TEXT,
                last_played_at TIMESTAMP
            )
        """)
        logger.info("Table 'user_statistics' created or already exists.")

        # Playlists (migrated from SQLite PLAYLIST_DB_PATH)
        c.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                is_public BOOLEAN DEFAULT FALSE,
                share_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Table 'playlists' created or already exists.")

        c.execute("""
            CREATE TABLE IF NOT EXISTS playlist_songs (
                playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
                song_id TEXT NOT NULL, -- Identifier for the song
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (playlist_id, song_id)
            )
        """)
        logger.info("Table 'playlist_songs' created or already exists.")

        # Issues (migrated from SQLite issues_db)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_issues (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Table 'user_issues' created or already exists.")

        c.execute("""
            CREATE TABLE IF NOT EXISTS issue_comments (
                id SERIAL PRIMARY KEY,
                issue_id INTEGER NOT NULL REFERENCES user_issues(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, -- Allow user deletion
                is_admin BOOLEAN DEFAULT FALSE,
                comment TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Table 'issue_comments' created or already exists.")

        # Lyrics Cache (migrated from SQLite LYRICS_CACHE_DB_PATH)
        c.execute("""
            CREATE TABLE IF NOT EXISTS lyrics_cache (
                song_id TEXT PRIMARY KEY,
                lyrics TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Table 'lyrics_cache' created or already exists.")

        # Create Indexes for performance
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_active_sessions_token ON active_sessions(session_token)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pending_otps_email_purpose ON pending_otps(email, purpose)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_local_songs_path ON local_songs(path)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_user_downloads_user_id ON user_downloads(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_listening_history_user_id ON listening_history(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_listening_history_song_id ON listening_history(song_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_user_play_queue_history_user_id ON user_play_queue_history(user_id, played_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_playlists_user_id ON playlists(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_playlist_songs_playlist_id ON playlist_songs(playlist_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_user_issues_user_id ON user_issues(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_issue_comments_issue_id ON issue_comments(issue_id)")
        logger.info("Indexes created or already exist.")

        conn.commit()
        logger.info("PostgreSQL database initialization complete.")

    except psycopg2.Error as e:
        logger.error(f"PostgreSQL database initialization error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            c.close()
            conn.close()

if __name__ == "__main__":
    print("Initializing PostgreSQL database schema...")
    # Ensure the database_files directory exists if any local file paths are still generated by os.path.join
    # For PostgreSQL, this is less critical for DB files themselves but might be for other app assets.
    os.makedirs(os.path.join(os.getcwd(), "database_files"), exist_ok=True) 
    init_postgres_db()
    print("Schema initialization process finished.")