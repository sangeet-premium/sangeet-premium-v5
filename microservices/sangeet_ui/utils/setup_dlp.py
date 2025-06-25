import os
import platform
import shutil
import stat
import requests
import logging
import re
from pathlib import Path
from tqdm import tqdm # For progress bar
from colorama import Fore, Style, init as colorama_init # For colored output

# --- Configuration ---
GITHUB_REPO_OWNER = "yt-dlp"
GITHUB_REPO_NAME = "yt-dlp"
BASE_URL = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases"

# Local directory structure (relative to the script's current working directory)
DRIVER_PARENT_DIR = Path("drivers")
DRIVER_SUBDIR = DRIVER_PARENT_DIR / "yt-dlp"

# Local executable name (base name, .exe will be appended for Windows)
LOCAL_EXECUTABLE_NAME_BASE = "driver"
LOCAL_VERSION_FILE = DRIVER_SUBDIR / "version.txt"

# --- Setup Logging & Colorama ---
colorama_init(autoreset=True) # Initialize Colorama

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format=f"{Fore.CYAN}%(asctime)s{Style.RESET_ALL} - {Fore.GREEN}%(levelname)s{Style.RESET_ALL} - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def get_platform_details():
    """Detects OS and architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    logger.info(f"Detected OS: {Fore.YELLOW}{system}{Style.RESET_ALL}, Architecture: {Fore.YELLOW}{machine}{Style.RESET_ALL}")
    return system, machine

def get_asset_and_local_names(system, machine):
    """
    Determines the GitHub asset name for the yt-dlp executable and
    the desired local name for the 'driver'.
    Returns: (github_asset_name, local_driver_name_with_extension)
    """
    local_driver_name = LOCAL_EXECUTABLE_NAME_BASE
    github_asset_name = None

    if system == "windows":
        github_asset_name = "yt-dlp.exe"
        local_driver_name = f"{LOCAL_EXECUTABLE_NAME_BASE}.exe"
    elif system == "darwin":  # macOS
        github_asset_name = "yt-dlp_macos" # Universal binary for arm64 and x64
        # local_driver_name remains "driver" (no extension typically)
    elif system == "linux":
        if machine in ["x86_64", "amd64"]:
            github_asset_name = "yt-dlp"
        elif machine == "aarch64":
            github_asset_name = "yt-dlp_linux_aarch64"
        elif machine in ["armv7l", "armv6l"]: # armv6l often uses armv7l builds
            github_asset_name = "yt-dlp_linux_armv7l"
        elif machine in ["i386", "i686"]:
            github_asset_name = "yt-dlp_linux_x86"
        else:
            logger.error(f"Unsupported Linux architecture: {machine}")
            return None, None
    else:
        logger.error(f"Unsupported OS: {system}")
        return None, None
    
    logger.info(f"Determined GitHub asset: {Fore.YELLOW}{github_asset_name}{Style.RESET_ALL}, Local name: {Fore.YELLOW}{local_driver_name}{Style.RESET_ALL}")
    return github_asset_name, local_driver_name

def get_latest_github_version_tag():
    """
    Fetches the latest release tag (version) from GitHub by following the /latest redirect.
    This avoids needing to parse the full API response for releases.
    """
    latest_release_url = f"{BASE_URL}/latest"
    try:
        logger.info(f"Fetching latest version tag from GitHub via redirect: {latest_release_url}")
        response = requests.get(latest_release_url, allow_redirects=True, timeout=15)
        response.raise_for_status()  # Raises an exception for bad status codes

        final_url = response.url
        # The final URL is typically like: https://github.com/yt-dlp/yt-dlp/releases/tag/YYYY.MM.DD.X
        version_match = re.search(r"/tag/([^/]+)$", final_url)
        if version_match:
            version_tag = version_match.group(1)
            logger.info(f"Latest version tag from GitHub: {Fore.MAGENTA}{version_tag}{Style.RESET_ALL}")
            return version_tag
        else:
            logger.error(f"Could not parse version tag from the final URL: {final_url}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching latest version tag: {e}")
        return None

def get_local_driver_version():
    """Reads the version from the local version.txt file."""
    if LOCAL_VERSION_FILE.exists():
        try:
            version = LOCAL_VERSION_FILE.read_text().strip()
            if version:
                logger.info(f"Local version found in {LOCAL_VERSION_FILE}: {Fore.BLUE}{version}{Style.RESET_ALL}")
                return version
            else:
                logger.warning(f"{LOCAL_VERSION_FILE} is empty.")
                return None
        except Exception as e:
            logger.error(f"Error reading local version file {LOCAL_VERSION_FILE}: {e}")
            return None
    logger.info(f"Local version file ({LOCAL_VERSION_FILE}) not found.")
    return None

def download_file_with_progress(url, destination_path):
    """Downloads a file and displays a progress bar."""
    logger.info(f"Starting download from: {Fore.YELLOW}{url}{Style.RESET_ALL}")
    logger.info(f"Saving to: {Fore.YELLOW}{destination_path}{Style.RESET_ALL}")
    try:
        response = requests.get(url, stream=True, timeout=60) # Increased timeout for large files
        response.raise_for_status()
        total_size_in_bytes = int(response.headers.get('content-length', 0))
        
        # Ensure destination directory exists
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        
        block_size = 8192 # 8KB
        progress_bar_desc = f"{Fore.GREEN}Downloading {destination_path.name}{Style.RESET_ALL}"

        with open(destination_path, 'wb') as file, tqdm(
            desc=progress_bar_desc,
            total=total_size_in_bytes,
            unit='iB',  # Use "iB" for KiB, MiB, etc.
            unit_scale=True,
            unit_divisor=1024, # For KiB, MiB
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]', # Richer format
            ncols=100 # Adjust to terminal width if needed
        ) as bar:
            for data in response.iter_content(block_size):
                bar.update(len(data))
                file.write(data)
        
        if total_size_in_bytes != 0 and bar.n != total_size_in_bytes:
            logger.error(f"{Fore.RED}Download error: Expected {total_size_in_bytes} bytes, got {bar.n} bytes.{Style.RESET_ALL}")
            if destination_path.exists():
                try: destination_path.unlink() # Clean up corrupted download
                except OSError: logger.error(f"Could not remove corrupted file: {destination_path}")
            return False

        logger.info(f"{Fore.GREEN}Download complete: {destination_path}{Style.RESET_ALL}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"{Fore.RED}Download failed: {e}{Style.RESET_ALL}")
        if destination_path.exists(): # Clean up partial download
            try: destination_path.unlink()
            except OSError: logger.error(f"Could not remove partially downloaded file: {destination_path}")
        return False
    except Exception as e:
        logger.error(f"{Fore.RED}An unexpected error occurred during download: {e}{Style.RESET_ALL}")
        if destination_path.exists():
            try: destination_path.unlink()
            except OSError: logger.error(f"Could not remove unexpected error file: {destination_path}")
        return False

def set_executable_permissions(filepath, current_system):
    """Sets executable permissions on non-Windows systems."""
    if current_system != "windows":
        try:
            # Get current permissions and add execute for user, group, and others
            current_mode = filepath.stat().st_mode
            new_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            filepath.chmod(new_mode)
            logger.info(f"Set executable permissions for {Fore.YELLOW}{filepath}{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"Failed to set permissions for {filepath}: {e}")

def main():
    logger.info(f"{Fore.CYAN}--- yt-dlp Driver Updater Script ---{Style.RESET_ALL}")
    
    current_os, current_arch = get_platform_details()
    github_asset, local_driver_filename = get_asset_and_local_names(current_os, current_arch)

    if not github_asset or not local_driver_filename:
        logger.critical("Could not determine required asset/driver names. Exiting.")
        return

    local_driver_path = DRIVER_SUBDIR / local_driver_filename
    
    # Ensure the base directory for the driver and version file exists
    DRIVER_SUBDIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Target GitHub asset name: {Fore.YELLOW}{github_asset}{Style.RESET_ALL}")
    logger.info(f"Local driver path will be: {Fore.YELLOW}{local_driver_path.resolve()}{Style.RESET_ALL}")
    logger.info(f"Local version file will be: {Fore.YELLOW}{LOCAL_VERSION_FILE.resolve()}{Style.RESET_ALL}")

    latest_github_version = get_latest_github_version_tag()
    if not latest_github_version:
        logger.error("Critical: Could not fetch the latest version tag from GitHub.")
        if not local_driver_path.exists():
            logger.critical(f"{Fore.RED}No local driver found and cannot check for updates. Please resolve network issues or place a driver manually.{Style.RESET_ALL}")
            return
        else:
            logger.warning(f"{Fore.YELLOW}Proceeding with the existing local driver as update check failed.{Style.RESET_ALL}")
            return # Exit because we can't be sure if it's the latest.

    current_local_version = get_local_driver_version()
    
    needs_download = False
    if not local_driver_path.exists():
        logger.warning(f"Local driver {Fore.RED}not found{Style.RESET_ALL} at {local_driver_path}.")
        needs_download = True
    elif not current_local_version:
        logger.warning(f"Local driver exists, but its version file ({LOCAL_VERSION_FILE.name}) {Fore.RED}is missing or empty{Style.RESET_ALL}. Re-downloading to ensure consistency.")
        needs_download = True
    elif current_local_version != latest_github_version:
        logger.info(f"New version available! Local: {Fore.BLUE}{current_local_version}{Style.RESET_ALL}, GitHub: {Fore.MAGENTA}{latest_github_version}{Style.RESET_ALL}.")
        needs_download = True
    else:
        logger.info(f"{Fore.GREEN}Local driver version ({current_local_version}) is already up-to-date.{Style.RESET_ALL}")

    if needs_download:
        logger.info(f"Preparing to download version {Fore.MAGENTA}{latest_github_version}{Style.RESET_ALL}...")
        # Construct the download URL: e.g., https://github.com/yt-dlp/yt-dlp/releases/download/YYYY.MM.DD/yt-dlp.exe
        download_url = f"{BASE_URL}/download/{latest_github_version}/{github_asset}"
        
        # If an old driver executable exists, remove it before downloading the new one
        if local_driver_path.exists():
            try:
                logger.info(f"Removing old driver at {local_driver_path} before update...")
                local_driver_path.unlink()
            except OSError as e:
                logger.error(f"{Fore.RED}Could not remove old driver {local_driver_path}: {e}. Please remove it manually and retry.{Style.RESET_ALL}")
                return # Stop if we can't remove the old one

        if download_file_with_progress(download_url, local_driver_path):
            set_executable_permissions(local_driver_path, current_os)
            try:
                LOCAL_VERSION_FILE.write_text(latest_github_version)
                logger.info(f"Updated local version file {LOCAL_VERSION_FILE.name} to: {Fore.MAGENTA}{latest_github_version}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"Error writing local version file {LOCAL_VERSION_FILE.name}: {e}")
            logger.info(f"{Fore.GREEN}Driver has been successfully downloaded/updated to version {latest_github_version}!{Style.RESET_ALL}")
            logger.info(f"Location: {Fore.YELLOW}{local_driver_path.resolve()}{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}Failed to download the new driver version. Please check logs and network connection.{Style.RESET_ALL}")
    else:
        logger.info(f"No download needed. Current driver: {Fore.YELLOW}{local_driver_path.resolve()}{Style.RESET_ALL} (Version: {Fore.BLUE}{current_local_version}{Style.RESET_ALL})")

if __name__ == "__main__":
    main()