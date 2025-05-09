#!/bin/bash

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <path-to-folder> <repo_id>"
  exit 1
fi

SOURCE_PATH=$(realpath "$1")
REPO_ID="$2"
CONTAINER_PATH="/work/$(basename "$SOURCE_PATH")"

export SOURCE_PATH
export CONTAINER_PATH
export REPO_ID

# Run with docker-compose
docker-compose up --build