#!/bin/sh
# Container entrypoint: wait for PostgreSQL, optionally migrate, then exec the command.
set -e

export POSTGRES_HOST="${POSTGRES_HOST:-db}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"

echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."

until python -c "
import os
import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
try:
    sock.connect((os.environ['POSTGRES_HOST'], int(os.environ['POSTGRES_PORT'])))
except OSError:
    sys.exit(1)
finally:
    sock.close()
"; do
  echo "PostgreSQL is unavailable - sleeping 1s"
  sleep 1
done

echo "PostgreSQL is reachable."

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Applying Alembic migrations..."
  alembic upgrade head
fi

echo "Starting: $*"
exec "$@"
