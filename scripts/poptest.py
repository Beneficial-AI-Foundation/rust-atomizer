#!/usr/bin/env python3
import json
import sys
import os
import csv
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
        atoms.append({
            "identifier": identifier,
            "display_name": display_name,
            "relative_path": rel_path,
            "deps": deps
        })
    return atoms

def save_as_json(atoms, out_path="atoms_debug.json"):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(atoms, f, indent=2)
    print(f"Saved JSON: {out_path}")

def save_as_csv(atoms, out_path="3212_atoms_debug.csv"):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["identifier", "display_name", "relative_path", "deps"])
        for atom in atoms:
            writer.writerow([
                atom["identifier"],
                atom["display_name"],
                atom["relative_path"],
                "; ".join(atom["deps"])
            ])
    print(f"Saved CSV: {out_path}")

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

    # Save outputs
    save_as_json(atoms)
    save_as_csv(atoms)

if __name__ == "__main__":
    main()

