use rust_atomizer::scip_to_call_graph_json::{parse_scip_json, build_call_graph, write_call_graph_as_atoms_json};
use std::env;
use std::process::Command;
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: {} <path-to-folder> <repo_id>", args[0]);
        std::process::exit(1);
    }

    let folder_path = &args[1];
    let repo_id = &args[2];
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

    // Call the Python script with the JSON file and repo_id
    println!("Running: populate_atomsdeps_grouped_rust.py {} {}", json_output_path, repo_id);
    let python_status = Command::new("python3")
        .arg("scripts/populate_atomsdeps_grouped_rust.py")
        .arg(repo_id)
        .arg(&json_output_path)
        .status()?;
    
    if !python_status.success() {
        eprintln!("Failed to run Python script");
        std::process::exit(1);
    }
    println!("Python script completed successfully");

    Ok(())
}