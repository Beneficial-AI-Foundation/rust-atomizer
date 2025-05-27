use rust_atomizer::scip_to_call_graph_json::{parse_scip_json, build_call_graph, write_call_graph_as_atoms_json};
use std::env;
use std::process::Command;
use std::path::Path;
use std::fs;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: {} <path-to-folder> <repo_id>", args[0]);
        std::process::exit(1);
    }

    let folder_path = &args[1];
    let repo_id = &args[2];

    // Check if Cargo.toml exists, if not create one for standalone Rust files
    let cargo_toml_path = Path::new(folder_path).join("Cargo.toml");
    if !cargo_toml_path.exists() {
        // Look for .rs files in the directory
        let entries = fs::read_dir(folder_path)?;
        let mut rust_files = Vec::new();
        
        for entry in entries {
            let entry = entry?;
            let path = entry.path();
            if path.is_file() && path.extension().and_then(|s| s.to_str()) == Some("rs") {
                if let Some(file_name) = path.file_stem().and_then(|s| s.to_str()) {
                    rust_files.push((file_name.to_string(), path.file_name().unwrap().to_str().unwrap().to_string()));
                }
            }
        }
        
        if !rust_files.is_empty() {
            // Create a basic Cargo.toml
            let package_name = rust_files[0].0.clone();
            let mut cargo_content = format!("[package]\nname = \"{}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n", package_name);
            
            for (name, file_name) in rust_files {
                cargo_content.push_str(&format!("[[bin]]\nname = \"{}\"\npath = \"{}\"\n\n", name, file_name));
            }
            
            fs::write(&cargo_toml_path, cargo_content)?;
            println!("Created Cargo.toml for standalone Rust files");
        }
    }
    
    let folder = Path::new(folder_path)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("output");
    let json_output_path = format!("{}.json", folder);
    let scip_file = "index.scip";
    let scip_json_file = "index_scip.json";

    // Run rust-analyzer scip <path_to_folder>
    println!("Running: rust-analyzer scip {}", folder_path);
    let status = Command::new("rust-analyzer")
        .arg("scip")
        .arg(folder_path)
        .status()?;
    if !status.success() {
        eprintln!("Failed to run rust-analyzer scip");
        std::process::exit(1);
    }

    // Run scip print --json > <folder>_scip.json
    println!("Running: scip print --json {} > {}", scip_file, scip_json_file);
    let scip_print = Command::new("scip")
        .arg("print")
        .arg("--json")
        .arg(&scip_file)
        .output()?;
    if !scip_print.status.success() {
        eprintln!("Failed to run scip print");
        std::process::exit(1);
    }
    std::fs::write(&scip_json_file, &scip_print.stdout)?;

    println!("Parsing SCIP JSON from {}...", scip_json_file);
    let scip_data = parse_scip_json(&scip_json_file)?;
    
    println!("Building call graph...");
    let call_graph = build_call_graph(&scip_data);

    if let Err(e) = write_call_graph_as_atoms_json(&call_graph, &json_output_path) {
        eprintln!("Failed to write atoms JSON: {}", e);
        std::process::exit(1);
    }
    println!("Atoms JSON written to {}", json_output_path);

    Ok(())
}