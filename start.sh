#!/bin/bash
# kevinl-openclaw startup script
# Serves tutorial at port 9101
cd "$(dirname "$0")"
exec python3 -m http.server 9101
