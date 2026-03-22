#!/bin/bash
cd "$(dirname "$0")"
echo "Stopping A.R.C.H.I.E. Node..."
docker compose down
echo ""
echo "Node stopped."
