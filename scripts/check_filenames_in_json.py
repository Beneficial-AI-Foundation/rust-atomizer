#!/usr/bin/env python3
"""
Script to generate no_atoms_filenames.txt from the most recent log file and 
check which filenames appear in elliptic-curves.json
"""

import json
import sys
import os
import glob
import re

def find_most_recent_log():
    """Find the most recent populate_atoms log file."""
    log_pattern = "logs/populate_atoms_*.log"
    log_files = glob.glob(log_pattern)
    
    if not log_files:
        print("Error: No populate_atoms log files found in logs/ directory")
        return None
    
    # Sort by modification time, most recent first
    log_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = log_files[0]
    
    print(f"Found {len(log_files)} log files, using most recent: {most_recent}")
    return most_recent

def extract_json_filename_from_log(log_file_path):
    """Extract the JSON filename from the log file."""
    json_filename = None
    
    try:
        with open(log_file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                # Look for the log line that shows the json_path parameter
                if "json_path:" in line:
                    # Extract json_path after "json_path: "
                    match = re.search(r'json_path:\s*(.+)$', line.strip())
                    if match:
                        json_path = match.group(1).strip()
                        # Extract just the filename from the path
                        json_filename = os.path.basename(json_path)
                        break
                
                # Alternative: Look for lines mentioning JSON file being processed
                elif "Processing completed for JSON file:" in line:
                    match = re.search(r'Processing completed for JSON file:\s*(.+)$', line.strip())
                    if match:
                        json_path = match.group(1).strip()
                        json_filename = os.path.basename(json_path)
                        break
                
                # Another alternative: Look for build_folders_to_files_mapping calls
                elif "build_folders_to_files_mapping" in line and ".json" in line:
                    # This is more complex parsing, but can catch cases where json file is mentioned
                    match = re.search(r'(\w+\.json)', line)
                    if match:
                        json_filename = match.group(1)
                        break
    
    except Exception as e:
        print(f"Error reading log file to extract JSON filename: {e}")
        return None
    
    return json_filename

def extract_no_atoms_filenames(log_file_path):
    """Extract filenames from 'No atoms found for filename' messages in the log."""
    filenames = []
    
    try:
        with open(log_file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if "No atoms found for filename:" in line:
                    # Extract filename after "No atoms found for filename: "
                    match = re.search(r'No atoms found for filename:\s*(.+)$', line.strip())
                    if match:
                        filename = match.group(1).strip()
                        filenames.append(filename)
    
    except FileNotFoundError:
        print(f"Error: Log file {log_file_path} not found")
        return []
    except Exception as e:
        print(f"Error reading log file {log_file_path}: {e}")
        return []
    
    return filenames

def generate_no_atoms_file(filenames):
    """Generate no_atoms_filenames.txt from extracted filenames."""
    output_file = 'no_atoms_filenames.txt'
    
    try:
        with open(output_file, 'w') as f:
            for filename in sorted(set(filenames)):  # Remove duplicates and sort
                f.write(f"{filename}\n")
        
        print(f"Generated {output_file} with {len(set(filenames))} unique filenames")
        return True
    
    except Exception as e:
        print(f"Error writing {output_file}: {e}")
        return False

def main():
    print("=== STEP 1: Generating no_atoms_filenames.txt from most recent log ===")
    
    # Find the most recent log file
    log_file = find_most_recent_log()
    if not log_file:
        return 1
    
    # Extract the JSON filename from the log
    print(f"Extracting JSON filename from {log_file}...")
    json_filename = extract_json_filename_from_log(log_file)
    
    if not json_filename:
        print("Could not extract JSON filename from log file.")
        print("Falling back to default: elliptic-curves.json")
        json_filename = "elliptic-curves.json"
    else:
        print(f"Found JSON filename in log: {json_filename}")
    
    # Check if the JSON file exists
    if not os.path.exists(json_filename):
        print(f"Error: JSON file {json_filename} not found")
        return 1
    
    # Extract filenames from the log
    print(f"Extracting 'No atoms found for filename' entries from {log_file}...")
    filenames_from_log = extract_no_atoms_filenames(log_file)
    
    if not filenames_from_log:
        print("No 'No atoms found for filename' entries found in the log file")
        return 1
    
    print(f"Found {len(filenames_from_log)} entries in log file")
    
    # Generate the no_atoms_filenames.txt file
    if not generate_no_atoms_file(filenames_from_log):
        return 1
    
    print(f"\n=== STEP 2: Checking filenames against {json_filename} ===")
    
    # Read filenames from the generated file
    # Read filenames from the generated file
    print("Reading filenames from no_atoms_filenames.txt...")
    try:
        with open('no_atoms_filenames.txt', 'r') as f:
            filenames_to_check = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("Error: no_atoms_filenames.txt not found (this shouldn't happen)")
        return 1
    
    print(f"Found {len(filenames_to_check)} filenames to check")
    
    # Read and parse the JSON file (using filename extracted from log)
    print(f"Loading {json_filename}...")
    try:
        with open(json_filename, 'r') as f:
            json_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {json_filename} not found")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return 1
    
    print(f"Loaded {len(json_data)} entries from {json_filename}")
    
    # Extract all relative paths from the JSON
    json_relative_paths = set()
    for entry in json_data:
        if 'relative_path' in entry:
            json_relative_paths.add(entry['relative_path'])
    
    print(f"Found {len(json_relative_paths)} unique relative paths in JSON")
    
    # Check which filenames appear in the JSON
    found_filenames = []
    missing_filenames = []
    
    for filename in filenames_to_check:
        if filename in json_relative_paths:
            found_filenames.append(filename)
        else:
            missing_filenames.append(filename)
    
    # Print results
    print(f"\n=== RESULTS ===")
    print(f"Total filenames checked: {len(filenames_to_check)}")
    print(f"Found in {json_filename}: {len(found_filenames)}")
    print(f"NOT found in {json_filename}: {len(missing_filenames)}")
    
    if found_filenames:
        print(f"\n=== FOUND FILENAMES ({len(found_filenames)}) ===")
        for filename in sorted(found_filenames):
            print(f"✓ {filename}")
    
    if missing_filenames:
        print(f"\n=== MISSING FILENAMES ({len(missing_filenames)}) ===")
        for filename in sorted(missing_filenames):
            print(f"✗ {filename}")
    
    # Save results to files
    with open('found_in_json.txt', 'w') as f:
        for filename in sorted(found_filenames):
            f.write(f"{filename}\n")
    
    with open('missing_from_json.txt', 'w') as f:
        for filename in sorted(missing_filenames):
            f.write(f"{filename}\n")
    
    print(f"Results saved to:")
    print(f"- found_in_json.txt ({len(found_filenames)} entries)")
    print(f"- missing_from_json.txt ({len(missing_filenames)} entries)")
    
    print(f"\n=== SUMMARY ===")
    print(f"Log file processed: {log_file}")
    print(f"JSON file analyzed: {json_filename}")
    print(f"Generated no_atoms_filenames.txt with {len(set(filenames_from_log))} unique entries")
    print(f"JSON analysis complete - see results above")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
