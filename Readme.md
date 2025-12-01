# Rust Atomizer

A tool for analyzing Rust codebases and extracting code structure information (atoms and dependencies) using [verus-analyzer](https://github.com/verus-lang/verus-analyzer) and [scip](https://github.com/sourcegraph/scip/).

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
│   ├── scip_to_call_graph_json.rs  # Core SCIP parsing logic
│   └── verus_parser.rs        # Verus-aware source parser using verus_syn
├── scripts/                   # Python scripts
│   └── populate_atomsdeps_grouped_rust.py  # Database population script
├── logs/                      # Generated log files
│   ├── atomizer_*_*.log       # Rust atomizer logs
│   └── populate_atoms_*.log   # Python script logs
```

## How It Works

1. **SCIP Generation**: Uses [verus-analyzer](https://github.com/verus-lang/verus-analyzer) to generate SCIP files from Rust source code
2. **JSON Conversion**: Converts SCIP data to a structured JSON format containing atoms (code elements) and their relationships with [scip](https://github.com/sourcegraph/scip/)
3. **Function Body Extraction**: Uses [verus_syn](https://github.com/verus-lang/verus) to accurately parse Verus/Rust source files and extract complete function bodies, including:
   - All Verus-specific syntax (`requires`, `ensures`, `decreases`, `proof { }`, etc.)
   - Quantifiers (`forall|`, `exists|`)
   - Implications and spec operators (`==>`, `&&&`, `|||`, `=~=`)
   - Doc comments and attributes
4. **Logging**: Both Rust and Python components generate detailed logs for debugging and auditing
5. **Database Population**: Stores the extracted code structure in a MySQL database 

## Prerequisites

- Docker and Docker Compose
- MySQL database accessible at `127.0.0.1` with database name `verilib`
- Environment variable `DB_PASSWORD` set for MySQL connection

## Usage

Run the analysis on a Rust repository:

```bash
./run_compose.sh <rust_repo_path> <repo_id> [user_id]
```

### Parameters

- `<rust_repo_path>`: Path to the Rust repository you want to atomize
- `<repo_id>`: Numeric identifier for the repository in the database
- `[user_id]`: Optional user identifier (defaults to 460176 if not provided)

### Examples

```bash
# Using default user_id (460176)
./run_compose.sh /path/to/my-rust-project 123

# With custom user_id
./run_compose.sh /path/to/my-rust-project 123 789
```

### Direct Usage (Without Docker)

You can also run the `write_atoms` binary directly without Docker if you have the prerequisites installed locally:

```bash
cargo run --bin write_atoms <path-to-folder> <repo_id> [user_id]
```

**Prerequisites for direct usage:**
- Rust toolchain installed
- `verus-analyzer` installed and in your PATH
- `scip` CLI tool installed and in your PATH

**Arguments:**
- `<path-to-folder>`: Path to the folder containing Rust source code
- `<repo_id>`: Repository identifier (used for logging)
- `[user_id]`: Optional user identifier (defaults to `460176`)

**Example:**
```bash
cargo run --bin write_atoms ./curve25519-dalek curve25519-dalek
```

**Output location:** The generated JSON file is saved in the **current working directory** (where you run the command from) as `<folder_name>.json`. For example, if you analyze `./curve25519-dalek`, the output will be `curve25519-dalek.json` in your current directory.

## What Happens During Execution

1. **Docker Build**: Builds the analysis container with Rust toolchain, verus-analyzer, and SCIP tools
2. **SCIP Analysis**: 
   - Runs `verus-analyzer scip` on the target repository
   - Converts SCIP output to JSON format using the `write_atoms` binary
   - Generates timestamped log files in `logs/atomizer_{repo_id}_{timestamp}.log`
3. **Database Population**:
   - Parses the generated JSON file
   - Populates the database with code atoms (functions, files, folders)
   - Establishes dependency relationships between atoms
   - Associates all operations with the specified user_id
   - Generates timestamped log files in `logs/populate_atoms_{timestamp}.log`
4. **Log Aggregation**:
   - Combines both Rust and Python logs into a single database entry
   - Stores comprehensive execution logs in the `atomizerlogs` table with repo_id and user_id
   
## Output

- **JSON File**: `<repo_name>.json` containing structured code analysis
- **Log Files**: 
  - `logs/atomizer_{repo_id}_{timestamp}.log`: Rust processing logs
  - `logs/populate_atoms_{timestamp}.log`: Python processing logs
- **Database Records**: Code atoms and dependencies stored in MySQL tables:
  - `atoms`: Individual code elements with user_id association
  - `atomsdependencies`: Dependencies between elements in the `atoms` table
  - `reposfolders`: Folder structure
  - `codes`: File contents and metadata
  - `atomizerlogs`: Combined execution logs for debugging and auditing (includes repo_id and user_id)

## Logging Features

The tool provides comprehensive logging at multiple levels:

### Console Output
- Real-time progress updates during execution
- Immediate feedback for debugging

### File Logging
- **Rust Component**: Timestamped logs with session metadata including repo_id and user_id
- **Python Component**: Detailed database operation logs
- **Persistent Storage**: All logs preserved for later analysis

### Database Logging
- **Combined Logs**: Rust and Python logs merged into single database entries
- **User Association**: All log entries tagged with repo_id and user_id for tracking
- **Structured Format**: Clear separation between different execution phases
- **Audit Trail**: Complete record of all operations per repository and user

### Log Structure
Each database log entry contains:
```
=== RUST ATOMIZER LOGS ===
[timestamp] [level] message
...
=== END RUST ATOMIZER LOGS ===

=== PYTHON POPULATE SCRIPT LOGS ===
timestamp - component - level - message
...
=== END PYTHON POPULATE SCRIPT LOGS ===
```

## Dependencies

### Rust Crates
- **verus_syn**: Verus-extended Rust parser for accurate function body extraction
- **scip**: SCIP protocol handling
- **serde/serde_json**: JSON serialization
- **regex**: Pattern matching
- **chrono**: Timestamping for logs

### Docker Container
- Debian bookworm-slim base
- Rust toolchain (latest stable)
- verus-analyzer
- SCIP v0.5.2
- Python 3 with mysql-connector-python

### Database Schema
Expects MySQL tables: `atoms`, `codes`, `reposfolders`, `atomizerlogs` with specific schema for code analysis storage. All relevant tables should support user_id field for user association.

## Troubleshooting

- Ensure the target repository has valid Rust code
- Check that MySQL is running and accessible
- Verify `DB_PASSWORD` environment variable is set
- For repositories without `Cargo.toml`, the tool will automatically create one for standalone `.rs` files
- Check log files in the `logs/` directory for detailed error information
- Review the `atomizerlogs` table for complete execution history filtered by repo_id and user_id
- Enable debug mode by setting `DEBUG=true` environment variable for verbose logging
- If using a custom user_id, ensure it's a valid numeric identifier in your system

## Technical Notes

### Why verus_syn?

SCIP provides function locations (file and line number) but not the function body boundaries. We use `verus_syn` (a Verus-extended Rust parser) to extract accurate function spans because:

1. **Verus-specific syntax**: Standard Rust parsers cannot handle Verus constructs like `ensures`, `requires`, `forall|`, `==>`, `&&&`, etc.
2. **Accurate spans**: `verus_syn` provides exact start and end line numbers for each function, including doc comments and attributes
3. **Macro support**: Correctly parses functions inside `verus!` macros
4. **Maintainability**: Using a proper parser is more robust than regex/brace-counting approaches

The `verus_parser` module caches parsed files to avoid re-parsing and provides efficient function body lookups.
