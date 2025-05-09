import os
import json
import sys
from mysql.connector import connect as mysql_connect
from pathlib import Path

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
            print(str(e))
            time.sleep(1)
            try:
                connection.reconnect(attempts=3, delay=1)
                cursor = connection.cursor(dictionary=True)
                cursor.execute(command, data)
                if "UPDATE" in command or "INSERT" in command:
                    connection.commit()
                return [x for x in cursor]
            except Exception as e:
                print(str(e))
                attempts += 1
    raise Exception("Couldn't reconnect to Mysql DB.")

class PopulateAtomsDeps:
    def __init__(self, con):
        self.con = con

    def get_codes_ids(self, repo_id):
        query = """
            SELECT id, text, filename, user_id FROM codes WHERE repo_id = %s;
        """
        result = sql2(self.con, query, (repo_id,))
        return {
            row["id"]: {
                "text": row["text"],
                "filename": row["filename"],
                "user_id": row["user_id"],
            }
            for row in result
        }

    def populate_atoms_table(self, code_id, user_id, atoms_list):
        for atom in atoms_list:
            # Check if the molecule already exists
            check_query = """
                SELECT id FROM atoms WHERE identifier = %s;
            """
            result = sql2(self.con, check_query, (atom["parent_folder"],))
            if not result:
                insert_query_for_parent_folder = """
                    INSERT INTO atoms (code_id, identifier, statement_type, type, user_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s, NOW());
                """
                sql2(
                    self.con,
                    insert_query_for_parent_folder,
                    (
                        code_id,
                        atom["parent_folder"],
                        "folder",
                        "molecule",
                        user_id,
                    ),
                )
                # Retrieve the id of the newly inserted molecule
            result = sql2(self.con, check_query, (atom["parent_folder"],))
            molecule_id = result[0]["id"]
            # Check if the atom already exists
            check_query = """
                SELECT COUNT(*) as count FROM atoms WHERE code_id = %s AND identifier = %s;
            """
            result = sql2(self.con, check_query, (code_id, atom["identifier"]))
            if result[0]["count"] == 0:
                # Insert the atom if it doesn't exist
                insert_query = """
                    INSERT INTO atoms (code_id, identifier, statement_type, parent_id, type, text, user_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW());
                """
                sql2(
                    self.con,
                    insert_query,
                    (
                        code_id,
                        atom["identifier"],
                        atom["statement_type"],
                        molecule_id,
                        "atom",
                        atom["body"],
                        user_id,
                    ),
                )
                

    def populate_atoms_from_json(self, code_id, user_id, json_data):
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
            SELECT identifier FROM atoms 
            WHERE code_id = %s AND identifier IN ({placeholders});
        """
        params = [code_id] + identifiers
        result = sql2(self.con, check_query, tuple(params))
        
        # Create set of existing atom identifiers
        for row in result:
            existing_atoms.add(row["identifier"])
        
        # Filter atoms that don't exist yet
        for atom in atoms:
            if atom["identifier"] not in existing_atoms:
                new_atoms.append(atom)
                print(f"Adding atom: {atom['identifier']}")
            else:
                print(f"Atom already exists: {atom['identifier']}")
        
        # If we have new atoms to insert, process them in batch
        if new_atoms:
            self.populate_atoms_table_batch(code_id, user_id, new_atoms)
    
    def populate_atoms_table_batch(self, code_id, user_id, atoms_list):
        """
        Process and insert multiple atoms at once, grouping them by parent folder
        """
        if not atoms_list:
            return
            
        # Group atoms by parent folder
        atoms_by_parent = {}
        for atom in atoms_list:
            parent_folder = atom["parent_folder"]
            if parent_folder not in atoms_by_parent:
                atoms_by_parent[parent_folder] = []
            atoms_by_parent[parent_folder].append(atom)
        
        # Process each parent folder group
        for parent_folder, folder_atoms in atoms_by_parent.items():
            # Check if the molecule already exists
            check_query = """
                SELECT id FROM atoms WHERE identifier = %s;
            """
            result = sql2(self.con, check_query, (parent_folder,))
            
            # Insert parent folder if it doesn't exist
            if not result:
                insert_query_for_parent_folder = """
                    INSERT INTO atoms (code_id, identifier, statement_type, type, user_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s, NOW());
                """
                sql2(
                    self.con,
                    insert_query_for_parent_folder,
                    (
                        code_id,
                        parent_folder,
                        "folder",
                        "molecule",
                        user_id,
                    ),
                )
            
            # Get the parent folder ID
            result = sql2(self.con, check_query, (parent_folder,))
            molecule_id = result[0]["id"]
            
            # Prepare batch insert for atoms in this folder
            insert_query = """
                INSERT INTO atoms (code_id, identifier, statement_type, parent_id, type, text, user_id, timestamp)
                VALUES 
            """
            
            values = []
            params = []
            
            for atom in folder_atoms:
                values.append("(%s, %s, %s, %s, %s, %s, %s, NOW())")
                params.extend([
                    code_id,
                    atom["identifier"],
                    atom["statement_type"],
                    molecule_id,
                    "atom",
                    atom["body"],
                    user_id,
                ])
            
            # Execute batch insert if we have atoms
            if values:
                batch_query = insert_query + ", ".join(values)
                sql2(self.con, batch_query, tuple(params))

    def populate_atoms_deps_from_json(self, code_id, user_id, json_data):
        # Handle both formats: array or {"Atoms": [...]}
        data = json.loads(json_data)
        if isinstance(data, list):
            atoms = data
        elif "Atoms" in data:
            atoms = data["Atoms"]
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
            
        print(f"Processing {len(all_deps)} dependencies in batch")
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
            SELECT id, identifier FROM atoms 
            WHERE code_id = %s AND identifier IN ({placeholders});
        """
        
        # Execute the query to get all IDs at once
        params = [code_id] + identifier_list
        result = sql2(self.con, id_query, tuple(params))
        
        # Create a mapping from identifier to ID
        id_map = {row["identifier"]: row["id"] for row in result}
        
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
            print("No valid dependencies found (missing atom IDs)")
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
            print("All dependencies already exist in the database")
            return
            
        print(f"Inserting {len(new_deps)} new dependencies")
        
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
        print(f"Parent identifier: {parent_id}")
        child_id = sql2(self.con, id_query, (code_id, child_identifier))[0]["id"]
        print(f"Child identifier: {child_id}")
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
            
    def delete_todays_entries(self):
        """
        Delete all entries from atoms and atomsdependencies tables that have today's date or a future date as timestamp.
        """
        print("Deleting today's and future entries from atoms and atomsdependencies tables...")
        
        # Delete from atomsdependencies first to maintain referential integrity
        delete_deps_query = """
            DELETE FROM atomsdependencies 
            WHERE DATE(timestamp) >= CURDATE();
        """
        deps_count = sql2(self.con, "SELECT COUNT(*) as count FROM atomsdependencies WHERE DATE(timestamp) >= CURDATE();", ())[0]["count"]
        sql2(self.con, delete_deps_query, ())
        print(f"Deleted {deps_count} entries from atomsdependencies table")
        
        # Delete from atoms
        delete_atoms_query = """
            DELETE FROM atoms 
            WHERE DATE(timestamp) >= CURDATE();
        """
        atoms_count = sql2(self.con, "SELECT COUNT(*) as count FROM atoms WHERE DATE(timestamp) >= CURDATE();", ())[0]["count"]
        sql2(self.con, delete_atoms_query, ())
        print(f"Deleted {atoms_count} entries from atoms table")
        
        return atoms_count, deps_count

    def populate_all_atoms(self, repo_id, output_dir: Path, latex_mapping: Path):
        atomized_results = self.atomize_all_theories(repo_id, output_dir, latex_mapping)
        for code_id, result in atomized_results.items():
            json_data = result["json_data"]
            user_id = result["user_id"]
            self.populate_atoms_from_json(code_id, user_id, json_data)

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
            print(f"Filtering for filename: {filename}")
            print(f"Total atoms before filtering: {len(atoms_list)}")
            
            # Filter atoms where the identifier contains the filename
            filtered_atoms = []
            seen_identifiers = set()
            for atom in atoms_list:
                identifier = atom.get("identifier", "")
                if filename in identifier and identifier not in seen_identifiers:
                    filtered_atoms.append(atom)
                    seen_identifiers.add(identifier)
            
            print(f"Total atoms after filtering: {len(filtered_atoms)}")
            
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

    def populate_all_atoms_for_rust(self, repo_id, json_path):
        # Keep a set of atom identifiers that have already been processed
        # This will help avoid duplicate inserts across different code_ids
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
        atoms_cache_path = cache_dir / f"filename_to_atoms_{repo_id}_{json_path.stem}.json"

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
            print(f"Failed to load/create codes cache: {e}")
            # Fallback to fresh data without caching
            codes = {code_id: code_data for code_id, code_data in self.get_codes_ids(repo_id).items() 
                     if code_data["filename"].endswith(".rs")}
            
            # Convert bytes to string 
            for code_data in codes.values():
                if isinstance(code_data["text"], bytes):
                    code_data["text"] = code_data["text"].decode('utf-8', errors='replace')

        print(f"Nb of Codes: {len(codes)}")

        # Try to load filename_to_atoms from cache or create new mapping
        try:
            if atoms_cache_path.exists():
                with open(atoms_cache_path, "r", encoding="utf-8") as f:
                    filename_to_atoms = json.load(f)
            else:
                # Parse JSON content once
                # Parse atoms list from json_content
                try:
                    data = json.loads(json_content)
                    if isinstance(data, list):
                        atoms_list = data
                    elif "Atoms" in data:
                        atoms_list = data["Atoms"]
                    else:
                        raise ValueError("Invalid JSON structure: neither an array nor contains 'Atoms' key")
                except json.JSONDecodeError:
                    raise ValueError("Invalid JSON format")
                
                # Build a mapping from filename (without .rs) to atoms correctly
                filename_to_atoms = {}
                
                # For each file, filter atoms where identifier contains the filename
                for code_id, code_data in codes.items():
                    filename = code_data["filename"]
                    # Remove .rs extension if present
                    if filename.endswith(".rs"):
                        filename_base = filename[:-3]
                    else:
                        filename_base = filename
                    
                    # Filter atoms for this file
                    filtered_atoms = []
                    for atom in atoms_list:
                        identifier = atom.get("identifier", "")
                        if filename_base in identifier:
                            filtered_atoms.append(atom)
                    
                    # Store filtered atoms for this file
                    if filtered_atoms:
                        filename_to_atoms[filename] = filtered_atoms
                        #print(f"Found {len(filtered_atoms)} atoms for {filename}")
                    
                # Write cache file
                with open(atoms_cache_path, "w", encoding="utf-8") as f:
                    json.dump(filename_to_atoms, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to load/create atoms cache: {e}")
            # Do fallback processing without caching

        # Populate atoms and dependencies using the mapping
        for code_id, code_data in codes.items():
            filename = code_data["filename"]
            user_id = code_data["user_id"]
            atoms_for_file = filename_to_atoms.get(filename, [])
            if not atoms_for_file:
                continue
            
            # Filter out atoms that have already been processed
            new_atoms = []
            for atom in atoms_for_file:
                identifier = atom.get("identifier", "")
                if identifier and identifier not in processed_atom_identifiers:
                    new_atoms.append(atom)
                    processed_atom_identifiers.add(identifier)
            
            if not new_atoms:
                print(f"No new atoms to process for {filename} and code_id {code_id}")
                continue
                
            json_for_filename = json.dumps(new_atoms)
            print(f"Populating atoms for {filename} and code_id {code_id}")
            # Use the batch version instead of single-processing function
            self.populate_atoms_from_json(code_id, user_id, json_for_filename)

        # Second pass to populate dependencies after all atoms are created
        for code_id, code_data in codes.items():
            filename = code_data["filename"]
            user_id = code_data["user_id"]
            atoms_for_file = filename_to_atoms.get(filename, [])
            if not atoms_for_file:
                continue
            json_for_filename = json.dumps(atoms_for_file)
            # The populate_atoms_deps_from_json already uses batch processing
            self.populate_atoms_deps_from_json(code_id, user_id, json_for_filename)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python populate_atomsdeps_table_rust.py <repo_id> <json_path>")
        sys.exit(1)

    repo_id = int(sys.argv[1])
    json_path = Path(sys.argv[2])

    con = mysql_connect(
        user="root",
        password=os.getenv("DB_PASSWORD"),
        host="127.0.0.1",
        database="verilib",
    )
    populate_atoms_deps = PopulateAtomsDeps(con)
    #atoms_count, deps_count = populate_atoms_deps.delete_todays_entries()

    output_dir = Path(".")

    # Example usage of populate_all_atoms
    populate_atoms_deps.populate_all_atoms_for_rust(repo_id, json_path)
