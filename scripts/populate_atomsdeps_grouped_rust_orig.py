import os
import json
import sys
from mysql.connector import connect as mysql_connect
from pathlib import Path
import time
import traceback
import logging
from datetime import datetime
import glob

def sql2(connection, command, data):
    attempts = 0
    while attempts < 3:
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(command, data)
            if "UPDATE" in command or "INSERT" in command:
                connection.commit()
            return [x for x in cursor]
        except Exception as e:
            print(str(e))  # Keep this as print since it's outside the class
            time.sleep(1)
            try:
                connection.reconnect(attempts=3, delay=1)
                cursor = connection.cursor(dictionary=True)
                cursor.execute(command, data)
                if "UPDATE" in command or "INSERT" in command:
                    connection.commit()
                return [x for x in cursor]
            except Exception as e:
                print(str(e))  # Keep this as print since it's outside the class
                attempts += 1
    raise Exception("Couldn't reconnect to Mysql DB.")

class MemoryLogHandler(logging.Handler):
    """Custom log handler that stores logs in memory"""
    def __init__(self):
        super().__init__()
        self.log_entries = []
    
    def emit(self, record):
        # Format the log record and store it
        log_entry = self.format(record)
        self.log_entries.append(log_entry)
    
    def get_logs(self):
        """Return all collected logs as a single string"""
        return "\n".join(self.log_entries)
    
    def clear_logs(self):
        """Clear the collected logs"""
        self.log_entries.clear()
class PopulateAtomsDeps:
    def __init__(self, con, log_to_file, log_filename, log_level=logging.INFO):
        self.con = con
        self.msgs = []  # Collect messages throughout execution

        # Set up logger
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(log_level)

        # Create console handler if not already exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler) 

        # Create memory handler for capturing logs
        self.memory_handler = MemoryLogHandler()
        memory_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.memory_handler.setFormatter(memory_formatter)
        self.logger.addHandler(self.memory_handler)
        
        # Add file handler if requested
        if log_to_file:
            file_handler = logging.FileHandler(log_filename)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
            self.logger.info(f"Logging to file: {log_filename}")

    def get_captured_logs(self):
        """Get all logs captured in memory"""
        return self.memory_handler.get_logs()

    def clear_captured_logs(self):
        """Clear the captured logs from memory"""
        self.memory_handler.clear_logs()

    def read_atomizer_logs(self, repo_id):
        """
        Read the most recent atomizer log file for the given repo_id.
        
        Args:
            repo_id (int): The repository ID to look for in log files
            
        Returns:
            str: Content of the atomizer log file, or empty string if not found
        """
        try:
            # Look for atomizer log files matching the pattern
            log_pattern = f"logs/atomizer_{repo_id}_*.log"
            log_files = glob.glob(log_pattern)
            
            if not log_files:
                self.logger.warning(f"No atomizer log files found for repo_id {repo_id}")
                return ""
            
            # Sort by modification time (most recent first)
            log_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            most_recent_log = log_files[0]
            
            self.logger.info(f"Reading atomizer log file: {most_recent_log}")
            
            with open(most_recent_log, 'r', encoding='utf-8') as f:
                atomizer_content = f.read()
            
            self.logger.info(f"Successfully read {len(atomizer_content)} characters from atomizer log")
            return atomizer_content
            
        except Exception as e:
            self.logger.error(f"Failed to read atomizer log file: {e}")
            return ""
    
    def insert_captured_logs_to_db(self, repo_id, user_id):
        """Insert captured logs directly to database, prepending atomizer logs if available"""
        try:
            # Get the atomizer logs first
            atomizer_logs = self.read_atomizer_logs(repo_id)
            
            # Get the Python script logs
            python_logs = self.get_captured_logs()
            
            if not atomizer_logs and not python_logs.strip():
                self.logger.info("No logs to insert")
                return

            # Combine the logs: atomizer logs first, then Python logs
            combined_logs = ""
            
            if atomizer_logs:
                combined_logs += "=== RUST ATOMIZER LOGS ===\n"
                combined_logs += atomizer_logs
                combined_logs += "\n=== END RUST ATOMIZER LOGS ===\n\n"
            
            if python_logs.strip():
                combined_logs += "=== PYTHON POPULATE SCRIPT LOGS ===\n"
                combined_logs += python_logs
                combined_logs += "\n=== END PYTHON POPULATE SCRIPT LOGS ===\n"

            insert_query = """
                INSERT INTO atomizerlogs (repo_id, user_id, text, timestamp)
                VALUES (%s, %s, %s, NOW());
            """
            sql2(self.con, insert_query, (repo_id, user_id, combined_logs))
            self.logger.info(f"Inserted combined logs to atomizerlogs table for repo_id {repo_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to insert captured logs: {e}")
    

    def get_codes_ids(self, repo_id):
        # First, get all codes for the repo
        query = """
            SELECT id, text, filename, folder_id, user_id FROM codes WHERE repo_id = %s;
        """
        result = sql2(self.con, query, (repo_id,))

        # Collect all unique folder_ids
        folder_ids = set(row["folder_id"] for row in result if row.get("folder_id") is not None)
        
        # Get all folder information needed to build complete paths
        folder_id_to_info = {}
        if folder_ids:
            # Get all folders that we might need (including parent folders)
            all_folder_query = """
                SELECT id, name, parent_id FROM reposfolders;
            """
            all_folder_results = sql2(self.con, all_folder_query, ())
            folder_id_to_info = {row["id"]: {"name": row["name"], "parent_id": row["parent_id"]} for row in all_folder_results}

        def build_folder_path(folder_id):
            """Recursively build the complete folder path by following parent_id chain"""
            if not folder_id or folder_id not in folder_id_to_info:
                return ""
            
            folder_info = folder_id_to_info[folder_id]
            folder_name = folder_info["name"]
            parent_id = folder_info["parent_id"]
            
            if parent_id is None:
                # This is the root folder
                return folder_name
            else:
                # Recursively get parent path and append current folder
                parent_path = build_folder_path(parent_id)
                if parent_path:
                    return f"{parent_path}/{folder_name}"
                else:
                    return folder_name

        codes_dict = {}
        for row in result:
            folder_id = row.get("folder_id")
            
            # Build complete folder path
            if folder_id:
                folder_path = build_folder_path(folder_id)
                if folder_path:
                    prefixed_filename = f"{folder_path}/{row['filename']}"
                else:
                    prefixed_filename = row["filename"]
            else:
                prefixed_filename = row["filename"]
            
            codes_dict[row["id"]] = {
                "text": row["text"],
                "filename": prefixed_filename,
                "filepath": None,  # You can add filepath logic if needed
                "folder_id": folder_id,
                "user_id": row["user_id"],
            }
            self.logger.info(f"!!!!!Code ID {row['id']}: filename='{prefixed_filename}', folder_id={folder_id}, folder_path='{folder_path if folder_id else 'None'}'")
        
        self.logger.info(f"Retrieved {len(codes_dict)} codes from database")
        return codes_dict

    def populate_atoms_from_json(self, repo_id, code_id, user_id, json_data, files_ids_dict):
        try:
            # Handle both formats: array or {"Atoms": [...]}
            data = json.loads(json_data)
            if isinstance(data, list):
                atoms = data
            elif "Atoms" in data:
                atoms = data["Atoms"]
            else:
                raise ValueError("Invalid JSON format: neither an array nor contains 'Atoms' key")

            if not atoms:
                return
                
            # First, filter out atoms that already exist in the database
            existing_atoms = set()
            new_atoms = []
            
            # Get all identifiers
            identifiers = [atom["identifier"] for atom in atoms]
            
            # Batch check which atoms already exist
            placeholders = ", ".join(["%s"] * len(identifiers))
            check_query = f"""
                SELECT full_identifier FROM atoms 
                WHERE code_id = %s AND full_identifier IN ({placeholders});
            """
            params = [code_id] + identifiers
            result = sql2(self.con, check_query, tuple(params))
            
            # Create set of existing atom identifiers
            for row in result:
                existing_atoms.add(row["full_identifier"])
            
            # Filter atoms that don't exist yet
            for atom in atoms:
                if atom["identifier"] not in existing_atoms:
                    new_atoms.append(atom)
                    self.logger.debug(f"Adding atom: {atom['identifier']}")
                else:
                    self.logger.debug(f"Atom already exists: {atom['identifier']}")
            
            # If we have new atoms to insert, process them in batch
            if new_atoms:
                self.populate_atoms_table_batch(repo_id, code_id, user_id, new_atoms, files_ids_dict)
        
        except Exception as e:
            error_msg = f"Error in populate_atoms_from_json: {str(e)}\n{traceback.format_exc()}"
            self.logger.error(f"{error_msg} - repo_id={repo_id}, code_id={code_id}")

    def populate_atoms_table_batch(self, repo_id, code_id, user_id, atoms_list, files_ids_dict):
        """
        Process and insert multiple atoms at once, grouping them by file name
    
        Args:
            code_id (int): The ID of the code entry
            repo_id (int): The ID of the repository
            user_id (int): The ID of the user
            atoms_list (list): List of atom dictionaries to insert
            files_ids_dict (dict, optional): Mapping from file identifiers to their molecule IDs
                                             from populate_folder_structure_as_molecules
        """
        if not atoms_list:
            return
        
        # If files_ids_dict is None, initialize an empty dict
        if files_ids_dict is None:
            files_ids_dict = {}
        
        # Group atoms by file name
        atoms_by_file = {}
        for atom in atoms_list:
            relative_path = atom.get("relative_path")
            # Normalize path for consistency with files_ids_dict keys
            normalized_path = relative_path.replace("\\", "/")
            if normalized_path not in atoms_by_file:
                atoms_by_file[normalized_path] = []
            atoms_by_file[normalized_path].append(atom)
        
        # Process each file name group
        for file_path, file_atoms in atoms_by_file.items():
            molecule_id = None
            
            # First check if the file already exists in our files_ids_dict mapping
            # Use exact matching to prevent cross-contamination between files
            if file_path in files_ids_dict:
                molecule_id = files_ids_dict[file_path]
            else:
                # Second, check if a file molecule exists with code_id = 0 (repository-level)
                check_query_repo_level = """
                    SELECT id FROM atoms WHERE full_identifier = %s AND code_id = 0 AND repo_id = %s AND type = 'molecule';
                """
                result = sql2(self.con, check_query_repo_level, (file_path, repo_id))
                
                if result:
                    molecule_id = result[0]["id"]
                else:
                    
                    # Check if the molecule already exists in the database with specific code_id
                    check_query = """
                        SELECT id FROM atoms WHERE full_identifier = %s AND code_id = %s AND repo_id = %s;
                    """
                    result = sql2(self.con, check_query, (file_path, code_id, repo_id))
                    
                    # Insert file name if it doesn't exist
                    if not result:
                        insert_query_for_file = """
                            INSERT INTO atoms (repo_id, code_id, identifier, full_identifier, statement_type, type, user_id, timestamp)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW());
                        """
                        # Extract file_name as the string after the last "/" in file_path
                        file_name = file_path.split("/")[-1]
                        sql2(
                            self.con,
                            insert_query_for_file,
                            (
                                repo_id,
                                code_id,
                                file_name,
                                file_path,
                                "file",
                                "molecule",
                                user_id,
                            ),
                        )
                    
                    # Get the file name ID
                    result = sql2(self.con, check_query, (file_path, code_id, repo_id))
                    if result:
                        molecule_id = result[0]["id"]
                    else:
                        self.logger.warning(f"Failed to get molecule ID for {file_path}")
                        continue
            
            # Prepare batch insert for atoms in this file
            insert_query = """
                INSERT INTO atoms (repo_id, code_id, identifier, full_identifier, statement_type, parent_id, type, text, user_id, timestamp)
                VALUES 
            """
            
            values = []
            params = []
            
            for atom in file_atoms:
                values.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())")
                params.extend([
                    repo_id,
                    code_id,
                    atom.get("display_name"),
                    atom.get("identifier"),
                    atom.get("statement_type"),
                    molecule_id,
                    "atom",
                    atom.get("body"),
                    user_id,
                ])
            
            # Execute batch insert if we have atoms
            if values:
                batch_query = insert_query + ", ".join(values)
                sql2(self.con, batch_query, tuple(params))
                self.logger.info(f"Inserted {len(file_atoms)} atoms for file {file_path}")
            else:
                self.logger.warning(f"No atoms to insert for file {file_path}")
                
    def populate_atoms_deps_from_json(self, code_id, user_id, json_data):
        # Handle both formats: array or {"Atoms": [...]}
        data = json.loads(json_data)
        if isinstance(data, list):
            atoms = data
        elif "Atoms" in data:
            atoms = data.get("Atoms")
        else:
            raise ValueError("Invalid JSON format: neither an array nor contains 'Atoms' key")

        # Collect all dependencies
        all_deps = []
        for atom in atoms:
            parent_identifier = atom["identifier"]
            for dep in atom.get("deps", []):
                all_deps.append((parent_identifier, dep))
        
        if not all_deps:
            return
            
        self.logger.info(f"Processing {len(all_deps)} dependencies in batch")
        self.populate_dependencies_table_batch(code_id, user_id, all_deps)
    
    def populate_dependencies_table_batch(self, code_id, user_id, dependency_pairs):
        """
        Insert multiple dependencies at once, more efficiently than one by one
        dependency_pairs is a list of (parent_identifier, child_identifier) tuples
        """
        if not dependency_pairs:
            return
        
        # First, get all the atom IDs we need in one query
        all_identifiers = set()
        for parent_id, child_id in dependency_pairs:
            all_identifiers.add(parent_id)
            all_identifiers.add(child_id)
        # Convert to list for SQL query
        identifier_list = list(all_identifiers)
        
        # Create a query with the right number of placeholders
        placeholders = ", ".join(["%s"] * len(identifier_list))
        id_query = f"""
            SELECT id, full_identifier FROM atoms 
            WHERE full_identifier IN ({placeholders});
        """
        
        # Execute the query to get all IDs at once
        params = identifier_list
        result = sql2(self.con, id_query, tuple(params))
        
        # Create a mapping from identifier to ID
        id_map = {row["full_identifier"]: row["id"] for row in result}
        
        # Check which combinations already exist in the database
        existing_deps = set()
        
        # Prepare list of parent-child ID pairs for dependencies that have IDs
        valid_deps = []
        for parent_identifier, child_identifier in dependency_pairs:
            if parent_identifier in id_map and child_identifier in id_map:
                parent_id = id_map[parent_identifier]
                child_id = id_map[child_identifier]
                valid_deps.append((parent_id, child_id))
        
        if not valid_deps:
            self.logger.debug("No valid dependencies found (missing atom IDs)")
            # Print which identifiers are missing
            missing = []
            for parent_identifier, child_identifier in dependency_pairs:
                if parent_identifier not in id_map:
                    missing.append(f"Missing parent: {parent_identifier} for child {child_identifier}")
                if child_identifier not in id_map:
                    missing.append(f"Missing child: {child_identifier} for parent {parent_identifier}") 
            if missing:
                self.logger.debug("Missing atom IDs:")
            for msg in missing:
                self.logger.debug(f"  {msg}")
            return
            
        # Get existing dependencies
        dep_placeholders = ", ".join(["(%s, %s)"] * len(valid_deps))
        check_query = f"""
            SELECT parentatom_id, childatom_id
            FROM atomsdependencies
            WHERE (parentatom_id, childatom_id) IN ({dep_placeholders});
        """
        
        # Flatten the list of tuples for the query parameters
        flat_params = [item for pair in valid_deps for item in pair]
        check_result = sql2(self.con, check_query, tuple(flat_params))
        
        # Convert result to set of tuples for easy checking
        for row in check_result:
            existing_deps.add((row["parentatom_id"], row["childatom_id"]))
        
        # Filter out dependencies that already exist
        new_deps = []
        for parent_id, child_id in valid_deps:
            if (parent_id, child_id) not in existing_deps:
                new_deps.append((parent_id, child_id))
                
        if not new_deps:
            self.logger.info("All dependencies already exist in the database")
            return
            
        self.logger.info(f"Inserting {len(new_deps)} new dependencies")
        
        # Prepare the batch insert query for dependencies
        insert_query = """
            INSERT INTO atomsdependencies (parentatom_id, childatom_id, user_id, timestamp)
            VALUES 
        """
        
        values = []
        params = []
        
        for parent_id, child_id in new_deps:
            values.append("(%s, %s, %s, NOW())")
            params.extend([parent_id, child_id, user_id])
        
        # Execute batch insert
        batch_query = insert_query + ", ".join(values)
        sql2(self.con, batch_query, tuple(params))

    def populate_dependencies_table(
        self, code_id, user_id, parent_identifier, child_identifier
    ):
        id_query = "SELECT id FROM atoms WHERE code_id = %s AND identifier = %s;"
        # Retrieve the ids for the parent and child identifiers
        parent_id = sql2(self.con, id_query, (code_id, parent_identifier))[0]["id"]
        self.logger.debug(f"Parent identifier: {parent_id}")
        child_id = sql2(self.con, id_query, (code_id, child_identifier))[0]["id"]
        self.logger.debug(f"Child identifier: {child_id}")
        # Check if the dependency already exists
        check_query = """
            SELECT COUNT(*) as count FROM atomsdependencies WHERE parentatom_id = %s AND childatom_id = %s;
        """
        result = sql2(self.con, check_query, (parent_id, child_id))
        if result[0]["count"] == 0:
            # Insert the dependency if it doesn't exist
            insert_query = """
                INSERT INTO atomsdependencies (parentatom_id, childatom_id, user_id, timestamp)
                VALUES (%s, %s, %s, NOW());
            """
            sql2(self.con, insert_query, (parent_id, child_id, user_id))
            
    def filter_json_by_filename(self, json_content, filename):
        """
        Filter the JSON content to keep only nodes where identifier contains the filename.
        The .rs extension is removed from the filename before checking.
        Handles both array structure and {"Atoms": [...]} structure.
        """
        try:
            data = json.loads(json_content)
            
            # Remove .rs extension from filename if present
            if filename.endswith(".rs"):
                filename = filename[:-3]
            
            # Handle the case where the JSON is an array
            if isinstance(data, list):
                atoms_list = data
            # Handle the case where the JSON has an "Atoms" key
            elif "Atoms" in data:
                atoms_list = data["Atoms"]
            else:
                raise ValueError("Invalid JSON structure: neither an array nor contains 'Atoms' key")
            
            # Print debugging info
            self.logger.debug(f"Filtering for filename: {filename}")
            self.logger.debug(f"Total atoms before filtering: {len(atoms_list)}")
            
            # Filter atoms where the identifier contains the filename
            filtered_atoms = []
            seen_identifiers = set()
            for atom in atoms_list:
                identifier = atom.get("identifier", "")
                if filename in identifier and identifier not in seen_identifiers:
                    filtered_atoms.append(atom)
                    seen_identifiers.add(identifier)
            
            self.logger.debug(f"Total atoms after filtering: {len(filtered_atoms)}")
            
            # Return the filtered list as JSON
            return json.dumps(filtered_atoms)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format")

    def get_filepath(self, folder_id):
        filepath = ""
        query = """
            SELECT name, parent_id FROM reposfolders WHERE id = %s;
        """
        result = sql2(self.con, query, (folder_id,))
        if not result:
            raise ValueError(f"Folder ID {folder_id} not found.")
        filepath += result[0]["name"]    
        return result[0]["name"], result[0]["parent_id"]

    def build_folders_to_files_mapping(self, json_path):
        """
        Constructs a dictionary mapping folders to files from a Rust atoms JSON file.
        
        Args:
            json_path (Path): Path to the JSON file containing atoms data
            
        Returns:
            dict: Dictionary where keys are folder paths and values are lists of filenames 
                  contained in those folders
        """
        # Read and parse the JSON file
        with open(json_path, encoding='utf-8') as f:
            json_content = f.read()
        
        try:
            data = json.loads(json_content)
            if isinstance(data, list):
                atoms_list = data
            elif "Atoms" in data:
                atoms_list = data["Atoms"]
            else:
                raise ValueError("Invalid JSON structure: neither an array nor contains 'Atoms' key")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON format in file: {json_path}")
        
        # Initialize the dictionary
        folders_to_files = {}
        # Process each atom to extract file and folder information
        for atom in atoms_list:
            
            relative_path = atom.get("relative_path", "")
            file_name = atom.get("file_name", "")

            if not relative_path or not file_name:
                continue
            
            # Determine the folder path (everything before the filename)
            # Handle both Unix and Windows-style paths
            normalized_path = relative_path.replace("\\", "/")
            
            # Check if the path ends with the filename
            if normalized_path.endswith(file_name):
                folder_path = normalized_path[:-len(file_name)].rstrip("/")
            else:
                # If the relative_path doesn't end with the filename, extract directory
                folder_path = "/".join(normalized_path.split("/")[:-1])
            
            # Ensure we have a valid folder path
            if not folder_path:
                folder_path = "/"  # Root
            
            # Add the file to the appropriate folder in our mapping
            if folder_path not in folders_to_files:
                folders_to_files[folder_path] = []
            
            if file_name not in folders_to_files[folder_path]:
                folders_to_files[folder_path].append(file_name)
        
        self.logger.info(f"Identified {len(folders_to_files)} folders containing Rust files")
        return folders_to_files

    def populate_all_atoms_for_rust(self, repo_id, json_path, files_ids_dict):
        # Keep a set of atom identifiers that have already been processed for each code_id
        # This will help avoid duplicate inserts within the same code_id while allowing
        # the same atom to be associated with multiple code_ids
        processed_atom_identifiers = set()
        
        if not json_path.exists():
            raise FileNotFoundError(f"JSON output not found at: {json_path}\n")

        json_content = ""
        with open(json_path, encoding='utf-8') as f:
            json_content = f.read()

        # Cache file paths for storing/retrieving codes and filename_to_atoms
        cache_dir = Path(".cache_populate_atomsdeps")
        cache_dir.mkdir(exist_ok=True)
        codes_cache_path = cache_dir / f"codes_{repo_id}.json"
        
        # Try to load codes from cache or create new cache
        try:
            if codes_cache_path.exists():
                with open(codes_cache_path, "r", encoding="utf-8") as f:
                    codes = json.load(f)
                # Convert keys back to int if needed
                codes = {int(k): v for k, v in codes.items()}
            else:
                codes = {code_id: code_data for code_id, code_data in self.get_codes_ids(repo_id).items() 
                         if code_data["filename"].endswith(".rs")}
                
                # Convert bytes to string before JSON serialization
                for code_data in codes.values():
                    if isinstance(code_data["text"], bytes):
                        code_data["text"] = code_data["text"].decode('utf-8', errors='replace')
                
                # Clean the cache file first to avoid corrupted JSON
                with open(codes_cache_path, "w", encoding="utf-8") as f:
                    json.dump(codes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to load/create codes cache: {e}")
            # Fallback to fresh data without caching
            codes = {code_id: code_data for code_id, code_data in self.get_codes_ids(repo_id).items() 
                     if code_data["filename"].endswith(".rs")}
            
            # Convert bytes to string 
            for code_data in codes.values():
                if isinstance(code_data["text"], bytes):
                    code_data["text"] = code_data["text"].decode('utf-8', errors='replace')

        self.logger.info(f"Nb of Codes: {len(codes)}")
        
        # Debug: Show all filenames from codes
        self.logger.debug("=== ALL FILENAMES FROM CODES DATABASE ===")
        for code_id, code_data in codes.items():
            self.logger.debug(f"Code ID {code_id}: {code_data['filename']}")
        
        data = json.loads(json_content)
        if isinstance(data, list):
            atoms_list = data
        elif "Atoms" in data:
            atoms_list = data["Atoms"]
        else:
            raise ValueError("Invalid JSON structure: neither an array nor contains 'Atoms' key")
        
        # Debug: Show all unique relative_paths from JSON atoms
        self.logger.debug("=== ALL UNIQUE RELATIVE_PATHS FROM JSON ===")
        unique_paths = set()
        for atom in atoms_list:
            rp = atom.get("relative_path", "")
            if rp:
                unique_paths.add(rp)
        
        for path in sorted(unique_paths):
            self.logger.debug(f"JSON relative_path: {path}")
        
        # Debug: Check specifically for sm2/src/lib.rs
        self.logger.debug(f"Found {len([atom for atom in atoms_list if atom.get('relative_path', '') == 'sm2/src/lib.rs'])} atoms for sm2/src/lib.rs in JSON")
                
        # Build a mapping from filename (without .rs) to atoms correctly
        filename_to_atoms = {}
                
        # For each file, filter atoms where identifier contains the filename
        for code_id, code_data in codes.items():
            filename = code_data["filename"]
            self.logger.debug(f"Processing code_id {code_id} with filename: {filename}")
            
            # Filter atoms for this file
            filtered_atoms = []
            for atom in atoms_list:
                identifier = atom.get("identifier", "")
                relative_path = atom.get("relative_path", "")
                
                # Use strict exact matching to prevent cross-contamination between files
                # Only match if the relative_path exactly equals the filename
                if relative_path == filename:
                    filtered_atoms.append(atom)
                    self.logger.debug(f"Matched atom {identifier} to filename {filename} via exact path match")
                    
            # Store filtered atoms for this file
            if filtered_atoms:
                filename_to_atoms[filename] = filtered_atoms
                self.logger.info(f"Found {len(filtered_atoms)} atoms for {filename}")
            else:
                self.logger.warning(f"No atoms found for filename: {filename}")
                # Additional debugging: show what relative_paths are available that might be similar
                similar_paths = []
                filename_base = filename.split("/")[-1] if "/" in filename else filename
                for atom in atoms_list[:100]:  # Check first 100 atoms to avoid spam
                    rp = atom.get("relative_path", "")
                    if filename_base in rp or any(part in rp for part in filename.split("/")[-2:]):
                        similar_paths.append(rp)
                
                if similar_paths:
                    unique_similar = list(set(similar_paths))[:5]  # Show up to 5 unique similar paths
                    self.logger.debug(f"Similar paths found: {unique_similar}")

        # Debug: Show summary of filename_to_atoms mapping
        self.logger.info(f"Summary: Found atoms for {len(filename_to_atoms)} out of {len(codes)} files")
        for filename, atoms in filename_to_atoms.items():
            self.logger.debug(f"  {filename}: {len(atoms)} atoms")

        # Populate atoms and dependencies using the mapping
        for code_id, code_data in codes.items():
            filename = code_data["filename"]
            #filepath = code_data["filepath"]
            user_id = code_data["user_id"]
            atoms_for_file = filename_to_atoms.get(filename, [])
            if not atoms_for_file:
                continue
            
            # Filter out atoms that have already been processed for this specific code_id
            # Create a unique key combining code_id and identifier
            new_atoms = []
            for atom in atoms_for_file:
                identifier = atom.get("identifier", "")
                if identifier:
                    code_atom_key = f"{code_id}:{identifier}"
                    if code_atom_key not in processed_atom_identifiers:
                        new_atoms.append(atom)
                        processed_atom_identifiers.add(code_atom_key)
            
            if not new_atoms:
                self.logger.debug(f"No new atoms to process for {filename} and code_id {code_id}")
                continue
                
            json_for_filename = json.dumps(new_atoms)
            self.logger.info(f"Populating atoms for {filename} and code_id {code_id}")
            
            # Use the batch version instead of single-processing function
            self.populate_atoms_from_json(repo_id, code_id, user_id, json_for_filename, files_ids_dict)

        # Second pass to populate dependencies after all atoms are created
        for code_id, code_data in codes.items():
            filename = code_data["filename"]
            user_id = code_data["user_id"]
            atoms_for_file = filename_to_atoms.get(filename, [])
            if not atoms_for_file:
                self.logger.debug(f"No atoms found for {filename} and code_id {code_id}")
                continue
            json_for_filename = json.dumps(atoms_for_file)
            # The populate_atoms_deps_from_json already uses batch processing
            self.populate_atoms_deps_from_json(code_id, user_id, json_for_filename)

    def populate_folder_structure_as_molecules(self, user_id, repo_id, folders_to_files):
        """
        Adds folders and files as molecules in the atoms table, establishing
        a parent-child relationship between folders and their files.
        Uses batch operations for better performance.
        Uses 0 for code_id to make folders/files repository-level structures.
        
        Args:
            user_id (int): The ID of the user
            repo_id (int): The ID of the repository
            folders_to_files (dict): Dictionary mapping folder paths to lists of files
            
        Returns:
            dict: Mapping of identifiers to their database IDs
        """
        self.logger.info(f"Populating folder structure with {len(folders_to_files)} folders as molecules for repo {repo_id}")
        
        # Dictionary to track the ID of each inserted folder/file
        identifier_to_id = {}
        
        # First get all existing folders to avoid unnecessary checks
        all_folder_full_identifiers = []
        for folder_path in folders_to_files.keys():
            # Skip root folder
            if folder_path == "/":
                continue
            # Normalize folder path for full_identifier (remove trailing slash)
            folder_full_identifier = folder_path.rstrip("/")
            all_folder_full_identifiers.append(folder_full_identifier)
        
        # Create a query with the right number of placeholders for existing folder check
        if all_folder_full_identifiers:
            placeholders = ", ".join(["%s"] * len(all_folder_full_identifiers))
            check_query = f"""
                SELECT id, full_identifier FROM atoms 
                WHERE full_identifier IN ({placeholders})
                AND type = 'molecule' AND statement_type = 'folder'
                AND code_id = 0 AND repo_id = %s;
            """
            params = all_folder_full_identifiers + [repo_id]
            result = sql2(self.con, check_query, tuple(params))
            
            # Store existing folder IDs
            for row in result:
                identifier_to_id[row["full_identifier"]] = row["id"]
        
        # Sort folders by depth (shortest paths first) to ensure parents are created before children
        sorted_folders = sorted(folders_to_files.keys(), key=lambda x: x.count('/'))
        self.logger.debug(f"Sorted folders by depth: {sorted_folders}")

        # First, collect all unique folder paths that need to exist (including intermediate ones)
        all_required_folders = set()
        for folder_path in folders_to_files.keys():
            if folder_path == "/":
                continue
            
            # Add the folder itself
            all_required_folders.add(folder_path)
            
            # Add all parent folders
            parts = folder_path.rstrip("/").split("/")
            for i in range(1, len(parts)):
                parent_path = "/".join(parts[:i])
                if parent_path:
                    all_required_folders.add(parent_path)

        # Sort all required folders by depth
        all_sorted_folders = sorted(all_required_folders, key=lambda x: x.count('/'))
        self.logger.info(f"All folders to create (including parents): {all_sorted_folders}")

        # Process folders in depth order to establish parent-child relationships
        for folder_path in all_sorted_folders:
            if folder_path == "/":
                continue
            
            folder_full_identifier = folder_path.rstrip("/")
            
            # Skip if folder already exists
            if folder_full_identifier in identifier_to_id:
                continue
            
            # Extract just the folder name from the full path
            folder_name = folder_full_identifier.split("/")[-1]
            
            # Determine parent folder
            parent_id = None
            if folder_path != "/" and "/" in folder_path:
                # Get parent folder path
                parent_folder_path = "/".join(folder_path.rstrip("/").split("/")[:-1])
                if not parent_folder_path:
                    parent_folder_path = "/"
                
                if parent_folder_path != "/":
                    parent_folder_full_identifier = parent_folder_path.rstrip("/")
                    parent_id = identifier_to_id.get(parent_folder_full_identifier)

            # Insert the folder with its parent_id
            insert_query = """
                INSERT INTO atoms (code_id, repo_id, identifier, full_identifier, statement_type, parent_id, type, user_id, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW());
            """
            sql2(self.con, insert_query, (0, repo_id, folder_name, folder_full_identifier, "folder", parent_id, "molecule", user_id))
            
            # Get the ID of the newly inserted folder
            id_query = """
                SELECT id FROM atoms 
                WHERE full_identifier = %s AND type = 'molecule' AND statement_type = 'folder'
                AND code_id = 0 AND repo_id = %s;
            """
            result = sql2(self.con, id_query, (folder_full_identifier, repo_id))
            if result:
                identifier_to_id[folder_full_identifier] = result[0]["id"]
                self.logger.debug(f"Added folder {folder_name} (full_identifier: {folder_full_identifier}) with parent_id {parent_id}")

        # Now collect all files that need to be inserted
        all_file_data = []
        for folder_path, files in folders_to_files.items():
            folder_full_identifier = folder_path.rstrip("/") if folder_path != "/" else "/"
            if folder_full_identifier == "/":
                folder_id = None
            else:
                folder_id = identifier_to_id.get(folder_full_identifier)
            
            for file_name in files:
                file_identifier = f"{folder_path}/{file_name}" if folder_path != "/" else file_name
                all_file_data.append((file_identifier, folder_id))

        # Check which files already exist
        all_file_identifiers = [file_data[0] for file_data in all_file_data]
        existing_file_ids = {}
        
        if all_file_identifiers:
            placeholders = ", ".join(["%s"] * len(all_file_identifiers))
            check_query = f"""
                SELECT id, full_identifier FROM atoms 
                WHERE full_identifier IN ({placeholders})
                AND type = 'molecule' AND statement_type = 'file'
                AND repo_id = %s;
            """
            params = all_file_identifiers + [repo_id]
            result = sql2(self.con, check_query, tuple(params))
            
            for row in result:
                existing_file_ids[row["full_identifier"]] = row["id"]
                identifier_to_id[row["full_identifier"]] = row["id"]

        # Filter out files that don't exist yet
        new_files = [(file_identifier, folder_id) for file_identifier, folder_id in all_file_data 
                    if file_identifier not in existing_file_ids]
        
        if new_files:
            self.logger.info(f"Adding {len(new_files)} new file molecules in batch")
            # Prepare batch insert query for files with 0 for code_id and include repo_id
            insert_query = """
                INSERT INTO atoms (code_id, repo_id, identifier, full_identifier, statement_type, parent_id, type, user_id, timestamp)
                VALUES 
            """
            values = []
            params = []
            
            for file_identifier, folder_id in new_files:
                file_name = file_identifier.split("/")[-1]
                values.append("(%s, %s, %s, %s, %s, %s, %s, %s, NOW())")
                params.extend([
                    0,  # Use 0 instead of NULL for code_id
                    repo_id,
                    file_name,
                    file_identifier,
                    "file",
                    folder_id,
                    "molecule",
                    user_id
                ])
            
            # Execute batch insert
            batch_query = insert_query + ", ".join(values)
            sql2(self.con, batch_query, tuple(params))
            
            # Get the IDs of the newly inserted files
            new_file_identifiers = [file_data[0] for file_data in new_files]
            if new_file_identifiers:
                placeholders = ", ".join(["%s"] * len(new_file_identifiers))
                id_query = f"""
                    SELECT id, full_identifier FROM atoms 
                    WHERE full_identifier IN ({placeholders})
                    AND type = 'molecule' AND statement_type = 'file'
                    AND code_id = 0 AND repo_id = %s;
                """
                params = new_file_identifiers + [repo_id]
                result = sql2(self.con, id_query, tuple(params))
                
                for row in result:
                    identifier_to_id[row["full_identifier"]] = row["id"]

        self.logger.info(f"Successfully populated {len(identifier_to_id)} folder and file molecules for repo {repo_id}")
        return identifier_to_id
        
    def set_code_id_for_files(self, repo_id):
        """
        Sets the code_id for file molecules based on their child atoms.
        For each file molecule, finds the first child atom and uses its code_id.
        
        Args:
            repo_id (int): The ID of the repository
        """
        self.logger.info(f"Setting code_id for file molecules in repo {repo_id}")
        
        # First, get all file molecules for this repo (both code_id = 0 and specific code_ids)
        file_query = """
            SELECT id, code_id, full_identifier FROM atoms 
            WHERE repo_id = %s AND type = 'molecule' AND statement_type = 'file';
        """
        file_result = sql2(self.con, file_query, (repo_id,))
        
        if not file_result:
            self.logger.info("No file molecules found")
            return
            
        # Separate files that need code_id updates (code_id = 0) from those that don't
        files_needing_update = [row for row in file_result if row["code_id"] == 0]
        files_with_code_id = [row for row in file_result if row["code_id"] != 0]
        
        self.logger.info(f"Found {len(files_needing_update)} file molecules with code_id=0 to update")
        self.logger.info(f"Found {len(files_with_code_id)} file molecules with specific code_ids")
        
        if not files_needing_update:
            self.logger.info("No file molecules with code_id = 0 found to update")
            return
            
        file_ids = [row["id"] for row in files_needing_update]
        
        # Build a mapping of file_id -> code_id by finding the first child atom for each file
        file_id_to_code_id = {}
        
        for file_id in file_ids:
            # Get the file identifier from our already-fetched data
            file_info = next((row for row in files_needing_update if row["id"] == file_id), None)
            file_identifier = file_info["full_identifier"] if file_info else f"ID_{file_id}"
            
            # Find the first atom that has this file as parent_id
            atom_query = """
                SELECT code_id FROM atoms 
                WHERE parent_id = %s AND type = 'atom' 
                LIMIT 1;
            """
            atom_result = sql2(self.con, atom_query, (file_id,))
            
            if atom_result:
                code_id = atom_result[0]["code_id"]
                file_id_to_code_id[file_id] = code_id
                self.logger.debug(f"Found code_id {code_id} for file {file_identifier}")
            else:
                self.logger.warning(f"No child atoms found for file ID {file_id} (file: {file_identifier})")
                
                # Additional debugging: check if there are atoms for files with specific code_ids
                specific_file_query = """
                    SELECT COUNT(*) as count FROM atoms a1
                    JOIN atoms a2 ON a1.parent_id = a2.id
                    WHERE a2.full_identifier = %s AND a2.type = 'molecule' AND a2.statement_type = 'file'
                    AND a1.type = 'atom' AND a2.repo_id = %s;
                """
                count_result = sql2(self.con, specific_file_query, (file_identifier, repo_id))
                if count_result and count_result[0]["count"] > 0:
                    self.logger.info(f"  ℹ️  Found {count_result[0]['count']} atoms for {file_identifier} in files with specific code_ids")
        
        if not file_id_to_code_id:
            self.logger.info("No file-to-code_id mappings found")
            return
            
        self.logger.info(f"Found code_id mappings for {len(file_id_to_code_id)} files")
        
        # Update files in batch using CASE statement
        # Build the CASE statement for batch update
        case_conditions = []
        file_ids_to_update = []
        
        for file_id, code_id in file_id_to_code_id.items():
            case_conditions.append(f"WHEN id = %s THEN %s")
            file_ids_to_update.extend([file_id, code_id])
        
        # Create the batch update query
        case_statement = " ".join(case_conditions)
        placeholders = ", ".join(["%s"] * len(file_id_to_code_id))
        
        update_query = f"""
            UPDATE atoms 
            SET code_id = CASE 
                {case_statement}
            END
            WHERE id IN ({placeholders});
        """
        
        # Prepare parameters: case conditions + file IDs for WHERE clause
        params = file_ids_to_update + list(file_id_to_code_id.keys())
        
        # Execute the batch update
        sql2(self.con, update_query, tuple(params))
        self.logger.info(f"Successfully updated code_id for {len(file_id_to_code_id)} file molecules")


if __name__ == "__main__":
    if len(sys.argv) not in [3, 4]:
        print("Usage: python populate_atomsdeps_table_rust.py <repo_id> <json_path> [user_id]")
        sys.exit(1)

    repo_id = int(sys.argv[1])
    json_path = Path(sys.argv[2])
    user_id = int(sys.argv[3]) if len(sys.argv) > 3 else 460176

    con = mysql_connect(
        user="root",
        password=os.getenv("DB_PASSWORD"),
        host="127.0.0.1",
        database="verilib",
    )

    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.INFO
    
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    # Create timestamped log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"populate_atoms_{timestamp}.log")
            
    populate_atoms_deps = PopulateAtomsDeps(con, log_to_file=True, log_filename=log_filename, log_level=log_level)
    
    # Log the input parameters and JSON file being processed
    populate_atoms_deps.logger.info(f"Starting populate_atomsdeps_grouped_rust.py with parameters:")
    populate_atoms_deps.logger.info(f"  repo_id: {repo_id}")
    populate_atoms_deps.logger.info(f"  json_path: {json_path}")
    populate_atoms_deps.logger.info(f"  user_id: {user_id}")
    populate_atoms_deps.logger.info(f"  JSON file exists: {json_path.exists()}")
    if json_path.exists():
        populate_atoms_deps.logger.info(f"  JSON file size: {json_path.stat().st_size} bytes")
        populate_atoms_deps.logger.info(f"  JSON file modified: {datetime.fromtimestamp(json_path.stat().st_mtime)}")
    
    output_dir = Path(".")

    folders_to_files = populate_atoms_deps.build_folders_to_files_mapping(json_path)
    user_id = 460176
    files_ids_dict = populate_atoms_deps.populate_folder_structure_as_molecules(user_id, repo_id, folders_to_files)
    # Example usage of populate_all_atoms
    populate_atoms_deps.populate_all_atoms_for_rust(repo_id, json_path, files_ids_dict)
    # Set code_id for file molecules based on their child atoms
    populate_atoms_deps.set_code_id_for_files(repo_id)

    # Insert captured logs directly from memory
    populate_atoms_deps.insert_captured_logs_to_db(repo_id, user_id)
    
    # Log completion
    populate_atoms_deps.logger.info(f"Successfully completed populate_atomsdeps_grouped_rust.py for repo_id {repo_id}")
    populate_atoms_deps.logger.info(f"Processing completed for JSON file: {json_path}")