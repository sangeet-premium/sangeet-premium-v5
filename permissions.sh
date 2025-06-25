#!/bin/sh
# -----------------------------------------------------------------------------
# WARNING: This script grants full read, write, and execute permissions (777)
# to all files and directories in its current location.
#
# This is intended to solve Docker volume permission issues in a local
# development environment ONLY.
#
# DO NOT USE THIS SCRIPT ON A PRODUCTION SERVER.
# -----------------------------------------------------------------------------

# Change to the directory where the script is located to ensure we are in the project root
cd "$(dirname "$0")"

echo "Applying full permissions (777) recursively to all files and directories..."
echo "Current directory: $(pwd)"

# Use sudo to ensure we have the rights to change permissions on all files,
# including those that might be owned by 'root' from inside a Docker container.
sudo chmod -R 777 .

echo "Permissions have been updated."