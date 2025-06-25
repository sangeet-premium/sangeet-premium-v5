#!/bin/bash
set -e

CONFIG_DIR="/home/nonroot/.cloudflared"
TUNNEL_CONFIG_FILE="$CONFIG_DIR/config.conf"
TUNNEL_URL_FILE="$CONFIG_DIR/tunnel.txt"
USE_NAMED_TUNNEL=true

# Ensure the config directory exists
mkdir -p "$CONFIG_DIR"

# Clean the tunnel URL file before starting
> "$TUNNEL_URL_FILE"

# ROBUSTNESS FIX: Check if the config file exists and contains a line
# starting with "tunnel:false", ignoring whitespace and comments.
if [ -f "$TUNNEL_CONFIG_FILE" ] && grep -q -E '^\s*tunnel:\s*false' "$TUNNEL_CONFIG_FILE"; then
  USE_NAMED_TUNNEL=false
fi

if [ "$USE_NAMED_TUNNEL" = "true" ]; then
  echo '✅ Starting named tunnel from config.yml...'
  # Add a helpful message to the file for named tunnels
  echo "Named tunnel active. URL is configured as music.sandeshai.in in config.yml" > "$TUNNEL_URL_FILE"
  exec cloudflared tunnel --config "$CONFIG_DIR/config.yml" run
else
  echo '⚠️ Starting temporary tunnel. The URL will be printed in the logs below and written to tunnel.txt.'

  # RELIABILITY FIX: Removed 'exec' to ensure the pipe to the 'while' loop works correctly.
  # The script will now run in the foreground, capturing logs to find the URL.
  cloudflared tunnel --url https://localhost:3400 --protocol http2 2>&1 | while IFS= read -r line; do
      # Print all logs to the docker compose output
      echo "$line"
      # Check for the trycloudflare.com URL
      if echo "$line" | grep -q 'trycloudflare.com'; then
          # Extract just the URL
          url=$(echo "$line" | grep -o 'https://[a-zA-Z0-9-]\+\.trycloudflare\.com' | head -n 1)
          if [ -n "$url" ]; then
              echo "Found temporary tunnel URL: $url"
              # Overwrite tunnel.txt with the found URL
              echo "$url" > "$TUNNEL_URL_FILE"
          fi
      fi
  done
fi