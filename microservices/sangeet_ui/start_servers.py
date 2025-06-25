import subprocess
import time
import os
import signal
import sys
from multiprocessing import Process, Value
from keygen import keygen
from utils import setup_dlp
from logger import log
import threading
from interconnect.config import config
# Import directory monitor
import waiter
from utils import dir_scan_plus
from database import database

logger = log.setup_logger(__name__)



with open("key.txt" , "w") as md:
    md.write(keygen.generate_secret_key())
md.close()

env_data_01 = config.get_env_data(os.path.join(os.getcwd() , "configs" , "ui" , "config.conf"))






# --- Configuration for each server ---
# You can adjust workers, host, and module:app as needed.
# The ports should match what your Nginx configuration expects.

SERVERS_CONFIG = [
    {
        "name": "Sangeet UI Server",
        "script_name": "sangeet_ui_server.py",
        "module_path": "sangeet_ui_server:server", # Python import path to Flask app
        "port": 80, # Internal port Nginx proxies to for UI
        "workers": 1, # Number of Gunicorn workers
        "log_prefix": "ui_server"
    },
    {
        "name": "Sangeet Stream Server",
        "script_name": "sangeet_stream_server_b.py",
        "module_path": "sangeet_stream_server_b:stream_app",
        "port": 2300, # Internal port Nginx proxies to for Stream
        "workers": 1,
        "log_prefix": "stream_server"
    },
    {
        "name": "Sangeet Download Server",
        "script_name": "sangeet_download_server_b.py",
        "module_path": "sangeet_download_server_b:bp",
        "port": 2301, # Internal port Nginx proxies to for Download
        "workers": 1,
        "log_prefix": "download_server"
    }
]

# Path to the directory containing the server .py files
# Assuming start.py is in the root of your project.
SERVER_FILES_DIR = os.getcwd()
GUNICORN_EXECUTABLE = "gunicorn" # Assumes gunicorn is in PATH

def run_gunicorn_server(config, running_flag):
    """
    Manages a Gunicorn server process.
    Restarts the server if it fails, as long as running_flag is set.
    """
    server_name = config["name"]
    module_path = config["module_path"]
    port = config["port"]
    workers = config["workers"]
    log_prefix = config["log_prefix"]

    # Construct Gunicorn command
    # We use gevent workers for good I/O performance, common for Flask apps.
    # Ensure gevent is installed (pip install gevent)
    gunicorn_command = [
        GUNICORN_EXECUTABLE,
        "-w", str(workers),
        "-k", "gevent",  # Using gevent worker class
        "--bind", f"0.0.0.0:{port}",
        "--access-logfile", f"-", # Log to stdout
        "--error-logfile", f"-",  # Log to stdout
        "--log-level", "info",
        "--name", f"{log_prefix}", # Name for process title
        module_path
    ]

    while running_flag.value == 1:
        print(f"[{server_name}] Starting server on port {port}...")
        print(f"[{server_name}] Command: {' '.join(gunicorn_command)}")
        try:
            # Start the Gunicorn process
            # The `cwd` argument is important if your Flask apps expect to be run
            # from their own directory (e.g., for relative paths to templates/static).
            # If your apps are self-contained or use absolute paths, cwd might not be needed
            # or could be the project root.
            # For simplicity, let's assume module_path handles imports correctly from project root.
            process = subprocess.Popen(gunicorn_command, cwd=os.getcwd()) # Run from project root
            process.wait()  # Wait for the process to complete

            if running_flag.value == 1: # If it exited and we are still supposed to be running
                print(f"[{server_name}] Server on port {port} exited with code {process.returncode}. Restarting in 5 seconds...")
                time.sleep(5)
            else:
                print(f"[{server_name}] Server on port {port} exited. Not restarting as flag is down.")
                break
        except FileNotFoundError:
            print(f"[{server_name}] ERROR: Gunicorn executable not found at '{GUNICORN_EXECUTABLE}'. Make sure Gunicorn is installed and in your PATH.")
            print(f"[{server_name}] Will not attempt to restart this server.")
            break
        except Exception as e:
            print(f"[{server_name}] An unexpected error occurred: {e}. Restarting in 5 seconds...")
            if process and process.poll() is None: # Check if process is still running
                process.terminate()
                process.wait()
            time.sleep(5)
        if running_flag.value == 0:
            print(f"[{server_name}] Shutdown signal received. Terminating process.")
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            break


def main():
    setup_dlp.main()
    processes = []
    running_flags = [] # To signal individual processes to stop

    # Shared value to signal all processes to stop
    global_running_flag = Value('i', 1)

    def signal_handler(sig, frame):
        print("\nSignal received, initiating shutdown...")
        global_running_flag.value = 0 # Signal all processes to stop
        for flag in running_flags:
            flag.value = 0 # Also set individual flags
        # Give processes a moment to shut down based on the flag
        time.sleep(2)
        # Then terminate any that haven't exited
        for p_info in processes:
            if p_info["process"].is_alive():
                print(f"Terminating process {p_info['name']} (PID: {p_info['process'].pid})...")
                p_info["process"].terminate() # Send SIGTERM
        # Wait for processes to terminate
        for p_info in processes:
            if p_info["process"].is_alive():
                p_info["process"].join(timeout=5) # Wait up to 5 seconds
            if p_info["process"].is_alive():
                print(f"Process {p_info['name']} did not terminate gracefully, killing...")
                p_info["process"].kill() # Force kill if still alive
        print("All server processes requested to stop.")
        sys.exit(0)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # kill command

    print("Starting Sangeet server processes...")
    print(f"Looking for server scripts in: {SERVER_FILES_DIR}")
    print(f"Using Gunicorn from: {GUNICORN_EXECUTABLE}")
    print("Press Ctrl+C to stop all servers.")

    for config in SERVERS_CONFIG:
        # Check if the actual .py script exists (optional, for user feedback)
        script_path = os.path.join(SERVER_FILES_DIR, config["script_name"])
        if not os.path.exists(script_path):
            print(f"WARNING: Script '{config['script_name']}' not found at '{script_path}'. Gunicorn will try to load module '{config['module_path']}' directly.")
        
        # Create a running flag for this specific process
        process_running_flag = Value('i', 1) # 1 for running, 0 for stop
        running_flags.append(process_running_flag)

        # Create a process for each server
        p = Process(target=run_gunicorn_server, args=(config, process_running_flag))
        processes.append({"name": config["name"], "process": p, "flag": process_running_flag})
        p.start()
        time.sleep(1) # Stagger starts slightly

    try:
        while global_running_flag.value == 1:
            for i, p_info in enumerate(processes):
                if not p_info["process"].is_alive() and p_info["flag"].value == 1:
                    print(f"Process for {p_info['name']} died unexpectedly and its flag is still up. Attempting to restart it (logic within run_gunicorn_server).")
                    # The restart logic is handled within run_gunicorn_server if flag is still 1
            time.sleep(5) # Check status every 5 seconds
    except KeyboardInterrupt: # Should be caught by signal_handler, but as a fallback
        print("Main loop KeyboardInterrupt, initiating shutdown via signal handler logic...")
        signal_handler(signal.SIGINT, None)
    finally:
        if global_running_flag.value == 1: # If loop exited for other reasons
             print("Main loop exited, ensuring all processes are stopped.")
             signal_handler(signal.SIGTERM, None) # Trigger shutdown

# sangeet_music_path_env = env_data_01.MUSIC_PATH
# sangeet_local_songs_path_env = env_data_01.LOCAL_SONGS_PATH

# raw_paths = []
# if sangeet_music_path_env:
#     raw_paths.extend(sangeet_music_path_env.split(';'))
# if sangeet_local_songs_path_env:
#     raw_paths.extend(sangeet_local_songs_path_env.split(';'))

# unique_cleaned_paths = sorted(list(set([p.strip() for p in raw_paths if p.strip()])))

# if not unique_cleaned_paths:
#     logger.warning("No music directories configured via MUSIC_PATH or LOCAL_SONGS_PATH. Using default: ['/music', '/local_songs']")
#     CONFIGURED_MUSIC_DIRS = ["/music", "/local_songs"] 
# else:
#     CONFIGURED_MUSIC_DIRS = unique_cleaned_paths
#     logger.info(f"Configured music directories to scan: {CONFIGURED_MUSIC_DIRS}")

# def task():
#     """Main startup task for the Sangeet UI server."""
    
#     # --- MOVED HERE: Create the thumbnail cache directory on startup ---
#     # This is the dedicated folder for our new on-demand thumbnail system.
#     thumbnail_dir = os.path.join(os.getcwd(), "thumbnails")
#     os.makedirs(thumbnail_dir, exist_ok=True)
#     logger.info(f"Ensured thumbnail cache directory exists at: {thumbnail_dir}")

#     logger.info("Starting Sangeet UI Server...")

#     # Start the directory monitor in a background thread
#     logger.info(f"Preparing to start directory monitoring for: {CONFIGURED_MUSIC_DIRS}")
#     monitor_thread = threading.Thread(
#         target=start_monitoring, 
#         args=(CONFIGURED_MUSIC_DIRS,), 
#         daemon=True
#     )
#     monitor_thread.start()
#     logger.info("Directory monitoring thread has been initiated.")



if __name__ == "__main__":
    # task()
    waiter.wait_for_db()
    #subprocess.Popen(f"cloudflared tunnel --config {os.path.join(os.getcwd() , "config.yml")} run 15e4d032-860b-41fd-b14c-6f02ab041750" , shell = True)
    
    paths_to_scan, music_dir = dir_scan_plus.get_paths(os.path.join(os.getcwd() , "configs" , "ui" , "config.conf"))
    scanner = dir_scan_plus.Local_songs_mon( directory_paths=paths_to_scan, music_path=music_dir)
    scanner.start()



    # This is crucial for multiprocessing on Windows, and good practice elsewhere.
    # It prevents child processes from re-executing the main module's code.
    main()
