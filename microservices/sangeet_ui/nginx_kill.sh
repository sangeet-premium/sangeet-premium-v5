#!/bin/bash

# ==============================================================================
# Script: remove_nginx.sh
# Description: This script completely removes Nginx and all its related
#              configuration files and dependencies from an Ubuntu system.
# WARNING: This script will permanently remove Nginx. Use with caution.
#          It is recommended to back up any important data before running.
# Usage: sudo ./remove_nginx.sh
# ==============================================================================

# Ensure the script is run with root privileges
if [ "$(id -u)" != "0" ]; then
   echo "This script must be run as root. Please use sudo." 1>&2
   exit 1
fi

echo "### Starting Nginx Removal Process ###"

# --- 1. Stop Nginx Service ---
echo ""
echo ">>> Step 1: Stopping and Disabling Nginx Service..."
if systemctl is-active --quiet nginx; then
    sudo systemctl stop nginx
    echo "Nginx service stopped."
else
    echo "Nginx service is not currently running."
fi

if systemctl is-enabled --quiet nginx; then
    sudo systemctl disable nginx
    echo "Nginx service disabled."
else
    echo "Nginx service is not enabled."
fi

# --- 2. Purge Nginx Packages ---
echo ""
echo ">>> Step 2: Purging Nginx Packages..."
# The 'purge' command removes packages and their configuration files.
# We use a wildcard (*) to catch all nginx related packages.
sudo apt-get purge nginx nginx-common nginx-full nginx-core -y > /dev/null 2>&1
sudo apt-get purge nginx* -y > /dev/null 2>&1
echo "Nginx packages purged."

# --- 3. Remove Unused Dependencies ---
echo ""
echo ">>> Step 3: Removing Unused Dependencies..."
# 'autoremove --purge' removes packages that were automatically installed
# to satisfy dependencies for other packages and are now no longer needed,
# along with their configuration files.
sudo apt-get autoremove --purge -y > /dev/null 2>&1
echo "Unused dependencies removed."

# --- 4. Remove Residual Nginx Directories ---
echo ""
echo ">>> Step 4: Removing Nginx Configuration and Log Directories..."
# Even after purging, some directories might remain. We remove them manually.
sudo rm -rf /etc/nginx
sudo rm -rf /var/log/nginx
sudo rm -rf /var/cache/nginx
sudo rm -f /usr/sbin/nginx # Use -f to avoid errors if it doesn't exist
sudo rm -f /usr/lib/systemd/system/nginx.service # Use -f
echo "Nginx directories removed."

# --- 5. Clean APT Cache ---
echo ""
echo ">>> Step 5: Cleaning APT Cache..."
# 'autoclean' removes downloaded package files that can no longer be
# downloaded and are largely useless.
sudo apt-get autoclean -y > /dev/null 2>&1
echo "APT cache cleaned."

# --- 6. Final Verification ---
echo ""
echo ">>> Step 6: Verifying Nginx Removal..."
if ! command -v nginx &> /dev/null
then
    echo "✅ Nginx appears to have been successfully removed."
else
    echo "⚠️ Nginx command still found. Manual check might be required."
    dpkg -l | grep nginx # List any remaining nginx packages
fi

echo ""
echo "### Nginx Removal Process Finished ###"
echo "It's recommended to reboot your system to ensure all changes take effect."
