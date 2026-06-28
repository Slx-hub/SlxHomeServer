#!/bin/bash
# Resets certbot to a clean slate.
# Stops the container and wipes the certbot data volume so the
# next `docker-compose up` triggers fresh initial cert generation.

echo "Stopping certbot..."
docker compose down

echo "Removing certbot data volume..."
docker compose down -v

echo "Done. Run 'docker-compose up -d' to generate new certs."
