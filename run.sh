#!/bin/bash
set -e

# Install the MySQL connector if not already installed
#pip3 install mysql-connector-python

# Your existing code
echo "PATH: $PATH"
echo "rust-analyzer location: $(which rust-analyzer 2>/dev/null || echo 'not found')"
echo "scip location: $(which scip 2>/dev/null || echo 'not found')"

# Run the write_atoms command with all arguments passed to this script
/usr/local/bin/write_atoms "$@"