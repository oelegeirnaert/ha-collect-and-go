#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Collect & Go add-on…"

exec python3 /app/main.py
