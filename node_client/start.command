#!/bin/bash
cd "$(dirname "$0")"
echo "Starting A.R.C.H.I.E. Node..."
docker compose up -d
echo ""
echo "Node started! You can close this window."
