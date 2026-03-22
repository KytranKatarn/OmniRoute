#!/bin/bash
cd "$(dirname "$0")"
echo "Updating A.R.C.H.I.E. Node..."
docker compose pull
docker compose up -d
echo ""
echo "Node updated!"
