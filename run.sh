#!/bin/bash
set -e

# Check if the path exists
if [ ! -d "$1" ]; then
  echo "Error: Directory '$1' does not exist or is not accessible"
  echo "Please make sure to mount the directory correctly when running the container."
  echo "Example: docker run -v /host/path:/container/path rust-atomizer /container/path repo_id"
  exit 1
fi

# Run write_atoms with the provided arguments
write_atoms "$@"