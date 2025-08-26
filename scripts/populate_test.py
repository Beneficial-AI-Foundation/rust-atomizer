#!/usr/bin/env python3
import json
import sys
import os
import logging

# Setup logging
logging.basicConfig(
    filename="populate_atoms_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def load_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def process_atoms(json_data):
    atoms = []
    for item in json_data:
        identifier = item.get("identifier")
        display_name = item.get("display_name")
        rel_path = item.get("relative_path")
        deps = item.get("deps", [])
        atoms.append((identifier, display_name, rel_path, deps))
    return atoms

def main():
    if len(sys.argv) < 2:
        print("Usage: python populate_atomsdeps_grouped_rust.py <json_file>")
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.exists(json_path):
        print(f"JSON file not found: {json_path}")
        sys.exit(1)

    data = load_json(json_path)
    atoms = process_atoms(data)

    print(f"Found {len(atoms)} atoms in {json_path}")
    logging.info("Found %d atoms in %s", len(atoms), json_path)

    for identifier, display_name, rel_path, deps in atoms:
        print(f"Atom: {identifier} | Name: {display_name} | File: {rel_path} | Deps: {len(deps)}")
        logging.debug(
            "Atom: %s | Name: %s | File: %s | Deps: %s",
            identifier, display_name, rel_path, deps,
        )

if __name__ == "__main__":
    main()

