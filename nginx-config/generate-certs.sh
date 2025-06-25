#!/bin/sh
set -e

SSL_PATH="/etc/nginx/ssl"
KEY_FILE="${SSL_PATH}/key.pem"
CERT_FILE="${SSL_PATH}/cert.pem"

# Check if the certificate already exists
if [ -f "$CERT_FILE" ]; then
  echo "SSL certificate already exists. Skipping generation."
  exit 0
fi

echo "SSL certificate not found. Generating a new self-signed certificate for localhost..."

mkdir -p "$SSL_PATH"

# Generate a certificate valid ONLY for localhost
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout "$KEY_FILE" -out "$CERT_FILE" \
  -subj "/CN=localhost"

echo "New SSL certificate generated successfully."