#!/bin/bash
# Distribute CANLII_API_KEY from platform .env to legal-watch on boston-2
# Run after filling in the key: CANLII_API_KEY=your_key_here in /mnt/archie_brain/.env
KEY=$(grep '^CANLII_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)
[ -z "$KEY" ] && { echo "CANLII_API_KEY is empty in .env — fill it in first"; exit 1; }
ssh -i ~/.ssh/id_ed25519 root@2.25.133.122 \
  "sed -i 's|^CANLII_API_KEY=.*|CANLII_API_KEY=$KEY|' /opt/archie-products/legal-watch/.env && \
   cd /opt/archie-products/legal-watch && docker compose up -d && echo 'distributed OK'"
