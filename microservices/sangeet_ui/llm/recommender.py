# sangeet_premium/llm/recommender.py (Modified for ytmusicapi only)

import os
import json
import logging
import redis
import random
import re # Import re for ID validation (used by ytmusicapi, good to have)
from functools import lru_cache

# --- Setup Logger FIRST ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Sangeet Imports (NO direct import of ytmusic from playback) ---
from utils import util
# We will pass the ytmusic instance as an argument where needed

# --- Global Variables & Initialization ---
redis_client = None

def init_redis_client():
    """Initializes the Redis client connection."""
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            redis_client.ping() # Verify connection
            logger.info("Recommender: Redis client initialized.")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Recommender: Failed to connect to Redis - {e}")
            redis_client = None
        except Exception as e:
             logger.error(f"Recommender: An unexpected error occurred during Redis init: {e}")
             redis_client = None

# --- Data Access Functions ---

def get_user_history_ids_for_exclusion(user_id, limit=30):
    """Fetches recent song IDs from Redis history for exclusion."""
    if not redis_client:
        logger.error("Cannot fetch user history: Redis client not initialized.")
        return []
    history_key = f"user_history:{user_id}"
    try:
        history_entries = redis_client.lrange(history_key, 0, limit - 1)
        song_ids = [json.loads(entry).get("song_id") for entry in history_entries if entry]
        return [sid for sid in song_ids if sid]
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Redis connection error fetching history for exclusion (user {user_id}): {e}")
        return []
    except json.JSONDecodeError as e:
         logger.error(f"Error decoding history entry for exclusion (user {user_id}): {e}")
         return []
    except Exception as e:
        logger.error(f"Error fetching history for exclusion (user {user_id}): {e}", exc_info=True)
        return []

@lru_cache(maxsize=128)
def get_song_details(song_id, ytmusic_client=None):
    """Fetches title and artist for a song ID (local or YouTube)."""
    details = {"id": song_id, "title": "Unknown Title", "artist": "Unknown Artist"}
    if redis_client:
        try:
            song_data = redis_client.hgetall(song_id)
            if song_data and "title" in song_data and "artist" in song_data:
                details["title"] = song_data["title"]
                details["artist"] = song_data["artist"]
                return details
        except redis.exceptions.ConnectionError as e:
            logger.warning(f"Redis connection error fetching details for {song_id}: {e}")
        except Exception as e:
             logger.warning(f"Error checking Redis details for {song_id}: {e}")

    if song_id.startswith("local-"):
         logger.debug(f"Checking local song details for {song_id} (primarily relies on Redis).")
         pass

    elif ytmusic_client:
        try:
            # Assuming ytmusic_client.get_song exists and returns a dict like before
            # This part might need adjustment based on the exact ytmusicapi library structure
            song_info = ytmusic_client.get_song(song_id) # Example, adjust if method name is different
            video_details = song_info.get("videoDetails", {})
            details["title"] = video_details.get("title", details["title"])
            artists_list = song_info.get("artists")
            if artists_list and isinstance(artists_list, list) and len(artists_list) > 0:
                 details["artist"] = artists_list[0].get("name", details["artist"])
            else: # Fallback if artists structure is different or not present
                 details["artist"] = video_details.get("author", details["artist"]) # Common fallback
            return details
        except Exception as e:
            if "not found" not in str(e).lower() and "invalid" not in str(e).lower():
                 logger.warning(f"Error fetching YTMusic details for {song_id} via API: {e}")
    elif not song_id.startswith("local-"):
         logger.warning(f"YTMusic client not provided to get_song_details for YouTube ID {song_id}")

    return details

def get_ytmusic_candidates(current_song_id, ytmusic_client, exclusion_ids=None, limit=30):
    """Fetches potential recommendation candidates from YTMusic."""
    if not ytmusic_client:
        logger.error("YTMusic API client not provided. Cannot fetch candidates.")
        return []

    exclusion_ids = set(exclusion_ids) if exclusion_ids else set()
    candidates = []
    seen_ids = set(exclusion_ids) # Initialize with songs to definitely exclude
    seen_ids.add(current_song_id)   # Exclude current song itself

    is_local = current_song_id.startswith("local-")
    use_watch_playlist = not is_local

    # Strategy 1: Use Watch Playlist (Only for YouTube IDs)
    if use_watch_playlist:
        try:
            logger.info(f"Fetching YTMusic watch playlist based on YT ID: {current_song_id}")
            # Ensure this method call is correct for your ytmusicapi library (e.g., ytmusic.get_watch_playlist)
            watch_playlist = ytmusic_client.get_watch_playlist(videoId=current_song_id, limit=limit)

            if watch_playlist and "tracks" in watch_playlist:
                for track in watch_playlist["tracks"]:
                    video_id = track.get("videoId")
                    if video_id and video_id not in seen_ids:
                        title = track.get('title', 'Unknown Title')
                        artist = "Unknown Artist"
                        if track.get("artists"): artist = track["artists"][0].get("name", "Unknown Artist")
                        
                        # ytmusicapi usually provides available tracks, but good to check if key exists
                        if track.get("isAvailable", True) or "isAvailable" not in track : 
                             candidates.append({"id": video_id, "title": title, "artist": artist, "source": "watch_playlist"})
                             seen_ids.add(video_id)
                             if len(candidates) >= limit: break
                logger.info(f"Got {len(candidates)} candidates from watch playlist.")
        except Exception as e:
            logger.warning(f"Error processing watch playlist for {current_song_id}: {e}")
            if "invalid videoId" in str(e).lower() or "no content" in str(e).lower():
                logger.warning(f"Watch playlist for {current_song_id} might be unavailable or ID is invalid.")
            # else, continue to search

    # Strategy 2: Use Search (Primary for local, fallback/additional for YT)
    if len(candidates) < limit:
        needed = limit - len(candidates)
        try:
            current_details = get_song_details(current_song_id, ytmusic_client=ytmusic_client)
            if current_details['title'] != "Unknown Title":
                search_query = f"{current_details['title']} {current_details['artist']}"
                if current_details['artist'] != "Unknown Artist" and not is_local:
                     # More weight to artist for related tracks from YT songs
                     search_query = f"{current_details['artist']} similar to {current_details['title']}"

                logger.info(f"Fetching {needed} candidates via YTMusic search: '{search_query}'")
                # Ensure this method call is correct (e.g., ytmusic.search)
                search_results = ytmusic_client.search(search_query, filter="songs", limit=needed + 10) # Fetch a bit more
                
                added_from_search = 0
                for track in search_results:
                    video_id = track.get("videoId")
                    if video_id and video_id not in seen_ids:
                        title = track.get('title', 'Unknown Title')
                        artist = "Unknown Artist"
                        if track.get("artists"): artist = track["artists"][0].get("name", "Unknown Artist")
                        
                        # Assuming 'songs' filter returns song items
                        # Add additional checks if resultType is present and needed
                        candidates.append({"id": video_id, "title": title, "artist": artist, "source": "search"})
                        seen_ids.add(video_id)
                        added_from_search +=1
                        if len(candidates) >= limit: break
                logger.info(f"Added {added_from_search} candidates from search. Total: {len(candidates)}")
            else:
                 logger.warning(f"Skipping YTMusic search for candidates as current song details are unknown ({current_song_id})")
        except Exception as e:
            logger.warning(f"Error searching YTMusic for candidates: {e}")

    logger.info(f"Returning {len(candidates)} YTMusic candidates.")
    return candidates


# --- Main Orchestration Function ---
def recommend_next_song(current_song_id, user_id, ytmusic_client):
    """
    Orchestrates the process using YTMusic candidates.
    Returns:
        - A dictionary {'type': 'available', 'id': song_id} if a song ID is recommended.
        - None if an error occurs or no recommendation could be made.
    """
    if not redis_client: init_redis_client() # For user history

    if not ytmusic_client:
         logger.error("YTMusic client instance was not provided to recommend_next_song.")
         return None

    logger.info(f"Recommending next song based on current: {current_song_id} for user: {user_id}")

    # 1. Get history IDs for exclusion (increase limit for better non-repetition)
    history_ids_to_exclude = get_user_history_ids_for_exclusion(user_id, limit=50) # e.g., exclude last 50 played
    
    exclude_ids = set(history_ids_to_exclude)
    exclude_ids.add(current_song_id) # Crucial: exclude the current song itself

    # 2. Get potential candidates from YTMusic
    # Fetch a decent number of candidates to have options.
    # `get_ytmusic_candidates` internally handles de-duplication based on `seen_ids`.
    ytmusic_candidates = get_ytmusic_candidates(
        current_song_id,
        ytmusic_client,
        exclusion_ids=list(exclude_ids),
        limit=20 # Fetch up to 20 diverse candidates
    )

    if not ytmusic_candidates:
         logger.info("No suitable YTMusic candidates found after applying exclusions.")
         return None

    # 3. Select a song. For simplicity, pick the first candidate.
    # The `get_ytmusic_candidates` function tries to get relevant songs from watch playlist first.
    # You could implement more sophisticated selection logic here if needed (e.g., random choice from top N).
    recommended_song = ytmusic_candidates[0]
    recommended_id = recommended_song.get("id")

    if recommended_id:
        logger.info(f"YTMusic Recommender: Selected song ID: {recommended_id} (Title: {recommended_song.get('title')}, Source: {recommended_song.get('source')})")
        return {'type': 'available', 'id': recommended_id}
    else:
        logger.error("YTMusic Recommender: Failed to get a valid ID from candidates.")
        return None

# Example of how you might call this (ensure ytmusic_client is initialized and passed)
# if __name__ == '__main__':
#     # This is a placeholder. You'd need a real ytmusic_client instance.
#     # from ytmusicapi import YTMusic # Assuming you use this library
#     # ytmusic = YTMusic() # Or YTMusic('oauth.json') for personalized results
#
#     class MockYTMusicClient:
#         def get_song(self, song_id):
#             if song_id == "dQw4w9WgXcQ":
#                 return {"videoDetails": {"title": "Never Gonna Give You Up", "author": "Rick Astley"}, "artists": [{"name": "Rick Astley"}]}
#             return {"videoDetails": {"title": "Unknown Title", "author": "Unknown Artist"}}
#
#         def get_watch_playlist(self, videoId, limit):
#             logger.info(f"Mock: get_watch_playlist for {videoId} with limit {limit}")
#             if videoId == "dQw4w9WgXcQ":
#                 return {"tracks": [
#                     {"videoId": "oHg5SJYRHA0", "title": "Video A", "artists": [{"name": "Artist A"}]},
#                     {"videoId": "HPj4D71iXqs", "title": "Video B", "artists": [{"name": "Artist B"}]},
#                     # Ensure no repetition with current song or major history here if possible
#                     {"videoId": "someOtherID", "title": "Another Song", "artists": [{"name": "Another Artist"}]},
#                 ]}
#             return {"tracks": []}
#
#         def search(self, query, filter, limit):
#             logger.info(f"Mock: search for '{query}' with filter '{filter}' limit {limit}")
#             return [
#                 {"videoId": "searchRes1", "title": "Search Result 1", "artists": [{"name": "Search Artist 1"}]},
#                 {"videoId": "searchRes2", "title": "Search Result 2", "artists": [{"name": "Search Artist 2"}]},
#             ]
#
#     mock_yt_client = MockYTMusicClient()
#     init_redis_client() # Initialize redis if you run this standalone
#
#     # Mock Redis history for testing exclusion
#     if redis_client:
#         user = "test_user"
#         redis_client.delete(f"user_history:{user}") # Clear previous
#         redis_client.rpush(f"user_history:{user}", json.dumps({"song_id": "oHg5SJYRHA0", "title": "Video A"}))
#
#     current_song = "dQw4w9WgXcQ" # Rick Astley
#     user_identifier = "test_user"
#
#     recommendation = recommend_next_song(current_song, user_identifier, mock_yt_client)
#
#     if recommendation:
#         print(f"Recommended next song ID: {recommendation['id']}")
#     else:
#         print("No recommendation could be made.")