#!/bin/bash
# Install ttyd for terminal-over-WebSocket
# This enables Claude CLI access from the browser

set -e

echo "=== Installing ttyd ==="

# Detect OS
if [ -f /etc/debian_version ]; then
    echo "Detected Debian/Ubuntu..."
    sudo apt-get update
    sudo apt-get install -y ttyd
elif [ -f /etc/redhat-release ]; then
    echo "Detected RHEL/CentOS..."
    sudo yum install -y epel-release
    sudo yum install -y ttyd
elif [ -f /etc/arch-release ]; then
    echo "Detected Arch Linux..."
    sudo pacman -S --noconfirm ttyd
else
    echo "Unknown OS, trying to build from source..."
    sudo apt-get install -y build-essential cmake git libjson-c-dev libwebsockets-dev
    git clone https://github.com/tsl0922/ttyd.git /tmp/ttyd
    cd /tmp/ttyd && mkdir build && cd build
    cmake ..
    make && sudo make install
fi

# Verify installation
if command -v ttyd &> /dev/null; then
    echo ""
    echo "=== ttyd installed successfully ==="
    ttyd --version
    echo ""
    echo "To start ttyd with Claude CLI:"
    echo "  ttyd -p 7681 claude"
else
    echo "ERROR: ttyd installation failed"
    exit 1
fi
