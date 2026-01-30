#!/bin/bash
export DB_HOST=192.168.1.200
export DB_PORT=5432
export DB_NAME=archie
export DB_USER=archie
export DB_PASSWORD="CTIf6MjCwuGUwVR_sWNNVIaMB6G7wnZ3RinJ_Cr6jwI"
exec /usr/bin/python3 /mnt/archie_brain/scripts/host_monitor.py --daemon --output /mnt/archie_brain/host_monitor_data.json
