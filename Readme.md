# Rust Atomizer

A tool for analyzing Rust codebases and extracting code structure information (atoms and dependencies) using SCIP (Source Code Intelligence Protocol) and rust-analyzer.

## Repository Structure

```
├── Cargo.toml                 # Rust project configuration
├── Dockerfile                 # Docker container configuration
├── docker-compose.yml         # Docker Compose configuration
├── run_compose.sh             # Main entry script
├── run.sh                     # Internal Docker script
├── src/                       # Rust source code
│   ├── lib.rs                 # Library root
│   ├── bin/
│   │   └── write_atoms.rs     # Main binary for SCIP processing
│   └── scip_to_call_graph_json.rs  # Core SCIP parsing logic
├── scripts/                   # Python scripts
│   └── populate_atomsdeps_grouped_rust.py  # Database population script
```

## How It Works

1. **SCIP Generation**: Uses [rust-analyzer](https://rust-analyzer.github.io/) to generate SCIP files from Rust source code
2. **JSON Conversion**: Converts SCIP data to a structured JSON format containing atoms (code elements) and their relationships with [scip](https://github.com/sourcegraph/scip/)
3. **Database Population**: Stores the extracted code structure in a MySQL database 

## Prerequisites

- Docker and Docker Compose
- MySQL database accessible at `127.0.0.1` with database name `verilib`
- Environment variable `DB_PASSWORD` set for MySQL connection

## Usage

Run the analysis on a Rust repository:

```bash
./run_compose.sh <rust_repo_path> <repo_id>
```

### Parameters

- `<rust_repo_path>`: Path to the Rust repository you want to atomize
- `<repo_id>`: Numeric identifier for the repository in the database

## What Happens During Execution

1. **Docker Build**: Builds the analysis container with Rust toolchain, rust-analyzer, and SCIP tools
2. **SCIP Analysis**: 
   - Runs `rust-analyzer scip` on the target repository
   - Converts SCIP output to JSON format using the `write_atoms` binary
3. **Database Population**:
   - Parses the generated JSON file
   - Populates the database with code atoms (functions, files, folders)
   - Establishes dependency relationships between atoms
   
## Output

- **JSON File**: `<repo_name>.json` containing structured code analysis
- **Database Records**: Code atoms and dependencies stored in MySQL tables:
  - `atoms`: Individual code elements
  - `atomsdependencies`: Dependencies between elements in the `atoms` table
  - `reposfolders`: Folder structure
  - `codes`: File contents and metadata

## Dependencies

### Docker Container
- Debian bookworm-slim base
- Rust toolchain (latest stable)
- rust-analyzer
- SCIP v0.5.2
- Python 3 with mysql-connector-python

### Database Schema
Expects MySQL tables: `atoms`, `codes`, `reposfolders` with specific schema for code analysis storage.

## Troubleshooting

- Ensure the target repository has valid Rust code
- Check that MySQL is running and accessible
- Verify `DB_PASSWORD` environment variable is set
- For repositories without `Cargo.toml`, the tool will automatically create one for standalone `.rs` files
