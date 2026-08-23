#!/bin/sh
# Double-click entry point for macOS Finder.
cd "$(dirname "$0")"
exec ./install.sh --yes
