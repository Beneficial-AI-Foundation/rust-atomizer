#!/bin/bash

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <path-to-folder> <repo_id> [user_id]"
  exit 1
fi

SOURCE_PATH=$(realpath "$1")  # Convert to absolute path
REPO_ID="$2"
USER_ID="${3:-460176}"  # Use third argument or default to 460176
CONTAINER_PATH="/work/$(basename "$SOURCE_PATH")"  # Map to container path

# Debugging output
echo "SOURCE_PATH: $SOURCE_PATH"
echo "CONTAINER_PATH: $CONTAINER_PATH"
echo "REPO_ID: $REPO_ID"
echo "USER_ID: $USER_ID"

export SOURCE_PATH
export CONTAINER_PATH
export REPO_ID
export USER_ID

# Run with docker-compose
docker-compose up --build

# After docker-compose, run the Python script to populate atoms/deps
# The JSON is generated as <repo_folder_name>.json in the source path
FOLDER_BASENAME=$(basename "$SOURCE_PATH")
JSON_PATH="$(pwd)/${FOLDER_BASENAME}.json"
echo "JSON_PATH: $JSON_PATH"
if [ -f "$JSON_PATH" ]; then
  echo "Running scripts/populate_atomsdeps_grouped_rust.py with repo_id=$REPO_ID, user_id=$USER_ID and json_path=$JSON_PATH"
  python3 scripts/populate_atomsdeps_grouped_rust.py "$REPO_ID" "$JSON_PATH" "$USER_ID"
else
  echo "JSON file not found at $JSON_PATH"
fi
