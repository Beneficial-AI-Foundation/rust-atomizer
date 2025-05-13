#!/bin/bash

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <path-to-folder> <repo_id>"
  exit 1
fi

SOURCE_PATH=$(realpath "$1")  # Convert to absolute path
REPO_ID="$2"
CONTAINER_PATH="/work/$(basename "$SOURCE_PATH")"  # Map to container path

# Debugging output
echo "SOURCE_PATH: $SOURCE_PATH"
echo "CONTAINER_PATH: $CONTAINER_PATH"
echo "REPO_ID: $REPO_ID"

export SOURCE_PATH
export CONTAINER_PATH
export REPO_ID

# Run with docker-compose
docker-compose up --build