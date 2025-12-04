use chrono::Utc;
use rust_atomizer::scip_to_call_graph_json::{
    build_call_graph, parse_scip_json, write_call_graph_as_atoms_json,
};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::process::Command;

struct AtomizerLogger {
    repo_id: String,
    user_id: String,
    messages: Vec<String>,
    log_file_path: String,
}

impl AtomizerLogger {
    fn new(repo_id: String, user_id: String) -> Result<Self, Box<dyn std::error::Error>> {
        // Create logs directory if it doesn't exist
        fs::create_dir_all("logs")?;

        // Create timestamped log filename
        let timestamp = Utc::now().format("%Y%m%d_%H%M%S");
        let log_file_path = format!("logs/atomizer_{}_{}.log", repo_id, timestamp);

        Ok(AtomizerLogger {
            repo_id,
            user_id,
            messages: Vec::new(),
            log_file_path,
        })
    }

    fn log(&mut self, level: &str, message: &str) {
        let timestamp = Utc::now().format("%Y-%m-%d %H:%M:%S UTC");
        let log_entry = format!("[{}] [{}] {}", timestamp, level, message);
        self.messages.push(log_entry.clone());
        // Also print to console for immediate feedback
        println!("{}", log_entry);
    }

    fn info(&mut self, message: &str) {
        self.log("INFO", message);
    }

    fn error(&mut self, message: &str) {
        self.log("ERROR", message);
    }

    fn warn(&mut self, message: &str) {
        self.log("WARN", message);
    }

    fn save_logs(&self) -> Result<(), Box<dyn std::error::Error>> {
        if self.messages.is_empty() {
            return Ok(());
        }

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_file_path)?;

        // Write header with metadata
        writeln!(file, "=== Atomizer Log Session ===")?;
        writeln!(file, "Repo ID: {}", self.repo_id)?;
        writeln!(file, "User ID: {}", self.user_id)?;
        writeln!(
            file,
            "Session Start: {}",
            Utc::now().format("%Y-%m-%d %H:%M:%S UTC")
        )?;
        writeln!(file, "================================")?;
        writeln!(file)?;

        // Write all log messages
        for message in &self.messages {
            writeln!(file, "{}", message)?;
        }

        writeln!(file)?;
        writeln!(file, "=== End of Session ===")?;
        writeln!(file)?;

        file.flush()?;
        Ok(())
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: {} <path-to-folder> <repo_id> [user_id]", args[0]);
        std::process::exit(1);
    }

    let folder_path = &args[1];
    let repo_id = &args[2];
    let user_id = args.get(3).map(|s| s.as_str()).unwrap_or("460176");

    let mut logger = AtomizerLogger::new(repo_id.clone(), user_id.to_string())?;
    logger.info(&format!(
        "Starting atomizer for repo_id: {}, user_id: {}",
        repo_id, user_id
    ));

    // Check if Cargo.toml exists, if not create one for standalone Rust files
    let cargo_toml_path = Path::new(folder_path).join("Cargo.toml");
    if !cargo_toml_path.exists() {
        logger.info(&format!(
            "Creating Cargo.toml for standalone Rust files in {}...",
            folder_path
        ));

        // Look for .rs files in the directory
        let entries = fs::read_dir(folder_path)?;
        let mut rust_files = Vec::new();

        for entry in entries {
            let entry = entry?;
            let path = entry.path();
            if path.is_file() && path.extension().and_then(|s| s.to_str()) == Some("rs") {
                if let Some(file_name) = path.file_stem().and_then(|s| s.to_str()) {
                    rust_files.push((
                        file_name.to_string(),
                        path.file_name().unwrap().to_str().unwrap().to_string(),
                    ));
                }
            }
        }

        if !rust_files.is_empty() {
            // Create a basic Cargo.toml
            let package_name = rust_files[0].0.clone();
            let mut cargo_content = format!(
                "[package]\nname = \"{}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n",
                package_name
            );

            for (name, file_name) in rust_files {
                cargo_content.push_str(&format!(
                    "[[bin]]\nname = \"{}\"\npath = \"{}\"\n\n",
                    name, file_name
                ));
            }

            fs::write(&cargo_toml_path, cargo_content)?;
            logger.info("Created Cargo.toml for standalone Rust files");
        }
    }

    let folder = Path::new(folder_path)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("output");
    let json_output_path = format!("{}.json", folder);
    let scip_file = "index.scip";
    let scip_json_file = "index_scip.json";

    // Run verus-analyzer scip <path_to_folder>
    logger.info(&format!("Running: verus-analyzer scip {}", folder_path));
    let output = Command::new("verus-analyzer")
        .arg("scip")
        .arg(folder_path)
        .output()?;
    if !output.status.success() {
        logger.warn(&format!(
            "Errors while running verus-analyzer scip: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    // Run scip print --json > <folder>_scip.json
    logger.info(&format!(
        "Running: scip print --json {} > {}",
        scip_file, scip_json_file
    ));
    let scip_print = Command::new("scip")
        .arg("print")
        .arg("--json")
        .arg(scip_file)
        .output()?;
    if !scip_print.status.success() {
        let error_msg = format!(
            "Failed to run scip print: {}",
            String::from_utf8_lossy(&scip_print.stderr)
        );
        logger.error(&error_msg);
        // Save logs before exiting
        logger.save_logs()?;
        std::process::exit(1);
    }
    std::fs::write(scip_json_file, &scip_print.stdout)?;

    logger.info(&format!("Parsing SCIP JSON from {}...", scip_json_file));
    let scip_data = parse_scip_json(scip_json_file)?;

    logger.info("Building call graph...");
    let call_graph = build_call_graph(&scip_data);

    if let Err(e) = write_call_graph_as_atoms_json(&call_graph, &json_output_path) {
        let error_msg = format!("Failed to write atoms JSON: {}", e);
        logger.error(&error_msg);
        // Save logs before exiting
        logger.save_logs()?;
        std::process::exit(1);
    }
    logger.info(&format!("Atoms JSON written to {}", json_output_path));

    // Save all logs to file at the end
    logger.save_logs()?;
    println!("Logs saved to file: {}", logger.log_file_path);

    Ok(())
}
