#!/usr/bin/env bash
# Démarre un Postgres jetable pour les tests SQL / RLS (pas de Docker ni de
# Supabase requis) et affiche son adresse sur la dernière ligne :
#   eval "$(scripts/test-postgres.sh start)"     # exporte SONA_TEST_DATABASE_URL
#   scripts/test-postgres.sh stop
set -euo pipefail

PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[ -n "$PGBIN" ] || PGBIN="$(dirname "$(command -v postgres)")"
DIR="${SONA_TEST_PGDIR:-/tmp/sona-test-pg}"
PORT="${SONA_TEST_PGPORT:-54329}"

as_pg() { if [ "$(id -u)" = 0 ]; then su postgres -s /bin/bash -c "$*"; else bash -c "$*"; fi; }

case "${1:-start}" in
  start)
    if [ ! -d "$DIR/data" ]; then
      mkdir -p "$DIR"
      [ "$(id -u)" = 0 ] && chown postgres:postgres "$DIR"
      as_pg "$PGBIN/initdb -D '$DIR/data' -A trust -U postgres >/dev/null"
    fi
    if ! as_pg "$PGBIN/pg_ctl -D '$DIR/data' status >/dev/null 2>&1"; then
      as_pg "$PGBIN/pg_ctl -D '$DIR/data' -o '-p $PORT -k $DIR -c listen_addresses=127.0.0.1 -c fsync=off' -l '$DIR/log' -w start >/dev/null"
    fi
    echo "export SONA_TEST_DATABASE_URL=postgres://postgres@127.0.0.1:$PORT/postgres"
    ;;
  stop)
    as_pg "$PGBIN/pg_ctl -D '$DIR/data' -m fast stop" || true
    ;;
esac
