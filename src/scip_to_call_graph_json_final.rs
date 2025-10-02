use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json;

// Re-using the SCIP data structures from our JSON parser
#[derive(Debug, Serialize, Deserialize)]
pub struct ScipIndex {
    pub metadata: Metadata,
    pub documents: Vec<Document>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Metadata {
    pub tool_info: ToolInfo,
    pub project_root: String,
    pub text_document_encoding: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ToolInfo {
    pub name: String,
    pub version: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Document {
    pub language: String,
    pub relative_path: String,
    pub occurrences: Vec<Occurrence>,
    #[serde(default)]
    pub symbols: Vec<Symbol>,
    pub position_encoding: i32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Occurrence {
    pub range: Vec<i32>,
    pub symbol: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub symbol_roles: Option<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Symbol {
    pub symbol: String,
    pub kind: i32,
    pub display_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub documentation: Option<Vec<String>>,
    pub signature_documentation: SignatureDocumentation,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enclosing_symbol: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SignatureDocumentation {
    pub language: String,
    pub text: String,
    pub position_encoding: i32,
}

/// Represents a node in the call graph
#[derive(Debug, Clone)]
pub struct FunctionNode {
    pub symbol: String,
    pub display_name: String,
    pub file_path: String,
    pub relative_path: String,  // Relative path from project root
    pub callers: HashSet<String>,  // Symbols that call this function
    pub callees: HashSet<String>,  // Symbols that this function calls
    pub range: Vec<i32>,  // Range of the function in the source file
    pub body: Option<String>,  // Optional body of the function
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Atom {
    pub identifier: String,
    pub statement_type: String,
    pub deps: Vec<String>,
    pub body: String,
    pub display_name: String,
    pub full_path: String,
    pub relative_path: String,
    pub file_name: String,
    pub parent_folder: String,
}   

/// Parse a SCIP JSON file
pub fn parse_scip_json(file_path: &str) -> Result<ScipIndex, Box<dyn std::error::Error>> {
    let path = Path::new(file_path);
    let contents = fs::read_to_string(path)?;
    let index: ScipIndex = serde_json::from_str(&contents)?;
    Ok(index)
}

/// Build a call graph from SCIP JSON data (Robust version)
pub fn build_call_graph(scip_data: &ScipIndex) -> HashMap<String, FunctionNode> {
    let mut call_graph: HashMap<String, FunctionNode> = HashMap::new();
    let mut function_symbols: HashSet<String> = HashSet::new();
    let mut symbol_enclosure: HashMap<String, String> = HashMap::new();
    let mut symbol_to_display_name: HashMap<String, String> = HashMap::new();

    // --- Pass 1: Collect all symbol information into lookup maps ---
    // We iterate through all symbols first to get a complete picture of the project.
    for doc in &scip_data.documents {
        for symbol in &doc.symbols {
            // Store the enclosure relationship for all symbols.
            if let Some(enclosing) = &symbol.enclosing_symbol {
                symbol_enclosure.insert(symbol.symbol.clone(), enclosing.clone());
            }

            // If the symbol is a function, store its kind and display name.
            if is_function_like(symbol.kind) {
                function_symbols.insert(symbol.symbol.clone());
                symbol_to_display_name.insert(
                    symbol.symbol.clone(),
                    symbol.display_name.clone().unwrap_or_else(|| "unknown".to_string())
                );
            }
        }
    }

    // --- Pass 2: Create FunctionNodes based on DEFINITION occurrences ---
    // This is the critical pass that correctly associates a function with its true source file.
    for doc in &scip_data.documents {
        let project_root = &scip_data.metadata.project_root;
        let rel_path_str = doc.relative_path.trim_start_matches('/');
        let abs_path_str = format!("{}/{}", project_root, rel_path_str);

        for occurrence in &doc.occurrences {
            let is_definition = occurrence.symbol_roles.unwrap_or(0) & 1 == 1;

            // If this occurrence is a definition for a known function symbol...
            if is_definition && function_symbols.contains(&occurrence.symbol) {
                // ...we create the node here, using THIS document's path.
                // Use .entry() to ensure we only create each node once.
                call_graph.entry(occurrence.symbol.clone()).or_insert_with(|| {
                    FunctionNode {
                        symbol: occurrence.symbol.clone(),
                        display_name: symbol_to_display_name
                            .get(&occurrence.symbol)
                            .cloned()
                            .unwrap_or_else(|| "unknown".to_string()),
                        // The path is from THIS document, which is the correct one.
                        file_path: abs_path_str.clone(),
                        relative_path: rel_path_str.to_string(),
                        callers: HashSet::new(),
                        callees: HashSet::new(),
                        // The range is from THIS occurrence.
                        range: occurrence.range.clone(),
                        body: None,
                    }
                });
            }
        }
    }

    // --- Pass 3: Build call graph edges using the enclosure hierarchy ---
    // This logic remains the same as our previous fix.
    for doc in &scip_data.documents {
        for occurrence in &doc.occurrences {
            let is_definition = occurrence.symbol_roles.unwrap_or(0) & 1 == 1;

            // We only care about function calls (not definitions).
            if !is_definition && function_symbols.contains(&occurrence.symbol) {
                let callee_symbol = &occurrence.symbol;

                let mut current_symbol = occurrence.symbol.clone();
                while let Some(enclosing_symbol) = symbol_enclosure.get(&current_symbol) {
                    if function_symbols.contains(enclosing_symbol) {
                        let caller_symbol = enclosing_symbol;

                        if caller_symbol != callee_symbol {
                            if let Some(caller_node) = call_graph.get_mut(caller_symbol) {
                                caller_node.callees.insert(callee_symbol.clone());
                            }
                            if let Some(callee_node) = call_graph.get_mut(callee_symbol) {
                                callee_node.callers.insert(caller_symbol.clone());
                            }
                        }
                        break;
                    }
                    current_symbol = enclosing_symbol.clone();
                }
            }
        }
    }

    // --- Pass 4: Extract function bodies from source files ---
    // This logic is unchanged but will now work correctly because the nodes have the correct paths.
    for node in call_graph.values_mut() {
        if !node.range.is_empty() {
            let clean_path = if node.file_path.starts_with("file://") {
                node.file_path.trim_start_matches("file://")
            } else {
                &node.file_path
            };

            if let Ok(contents) = fs::read_to_string(clean_path) {
                let lines: Vec<&str> = contents.lines().collect();
                let start_line = node.range[0] as usize;

                if start_line < lines.len() {
                    let mut body_lines = Vec::new();
                    let mut open_braces = 0;
                    let mut found_first_brace = false;

                    // Heuristic to find the real start of the function signature
                    let mut actual_start_line = start_line;
                    for i in (0..=start_line).rev() {
                        if lines[i].contains("fn ") || lines[i].contains("const fn ") {
                            actual_start_line = i;
                            break;
                        }
                    }

                    for line_idx in actual_start_line..lines.len() {
                        let line = lines[line_idx];
                        body_lines.push(line);

                        if !found_first_brace && line.contains('{') {
                            found_first_brace = true;
                        }

                        if found_first_brace {
                            open_braces += line.matches('{').count();
                            open_braces = open_braces.saturating_sub(line.matches('}').count());
                            if open_braces == 0 {
                                break;
                            }
                        }
                    }
                    node.body = Some(body_lines.join("\n"));
                }
            } else {
                println!("Failed to read file for body extraction: {}", clean_path);
            }
        }
    }
    call_graph
}
/// Build a call graph from SCIP JSON data
pub fn old_build_call_graph(scip_data: &ScipIndex) -> HashMap<String, FunctionNode> {
    let mut call_graph: HashMap<String, FunctionNode> = HashMap::new();
    let mut function_symbols: HashSet<String> = HashSet::new();
    let mut symbol_enclosure: HashMap<String, String> = HashMap::new();

    // First pass: Collect all function definitions, their locations, and the symbol hierarchy.
    for doc in &scip_data.documents {
        for symbol in &doc.symbols {
            // Store the enclosure relationship for all symbols. This builds our hierarchy map.
            if let Some(enclosing) = &symbol.enclosing_symbol {
                symbol_enclosure.insert(symbol.symbol.clone(), enclosing.clone());
            }

            // If the symbol is a function, create its node in the call graph.
            if is_function_like(symbol.kind) {
                function_symbols.insert(symbol.symbol.clone());

                let project_root = &scip_data.metadata.project_root;
                let rel_path = doc.relative_path.trim_start_matches('/');
                let abs_path = format!("{}/{}", project_root, rel_path);

                call_graph.insert(symbol.symbol.clone(), FunctionNode {
                    symbol: symbol.symbol.clone(),
                    display_name: symbol.display_name.clone().unwrap_or_else(|| "unknown".to_string()),
                    file_path: abs_path,
                    relative_path: rel_path.to_string(),
                    callers: HashSet::new(),
                    callees: HashSet::new(),
                    range: Vec::new(),  // Will be filled next
                    body: None,         // Will be filled in the third pass
                });
            }
        }
        
        // Also in the first pass, find the ranges for function definitions.
        for occurrence in &doc.occurrences {
            let is_definition = occurrence.symbol_roles.unwrap_or(0) & 1 == 1;
            if is_definition && function_symbols.contains(&occurrence.symbol) {
                if let Some(node) = call_graph.get_mut(&occurrence.symbol) {
                    node.range = occurrence.range.clone();
                }
            }
        }
    }

    // Second pass: Analyze occurrences to build the call graph edges using the enclosure hierarchy.
    for doc in &scip_data.documents {
        for occurrence in &doc.occurrences {
            let is_definition = occurrence.symbol_roles.unwrap_or(0) & 1 == 1;

            // We only care about function calls (i.e., not a definition).
            if !is_definition && function_symbols.contains(&occurrence.symbol) {
                let callee_symbol = &occurrence.symbol;
                
                // Robustly find the caller by walking up the enclosure tree from the call site.
                let mut current_symbol = occurrence.symbol.clone();
                while let Some(enclosing_symbol) = symbol_enclosure.get(&current_symbol) {
                    // Check if the enclosing symbol is a known function.
                    if function_symbols.contains(enclosing_symbol) {
                        let caller_symbol = enclosing_symbol;
                        
                        // We've found the calling function. Add the edge.
                        if caller_symbol != callee_symbol { // Avoid self-calls for now
                            // Update caller's callees
                            if let Some(caller_node) = call_graph.get_mut(caller_symbol) {
                                caller_node.callees.insert(callee_symbol.clone());
                            }
                            // Update callee's callers
                            if let Some(callee_node) = call_graph.get_mut(callee_symbol) {
                                callee_node.callers.insert(caller_symbol.clone());
                            }
                        }
                        // Stop traversing once we've found the immediate enclosing function.
                        break; 
                    }
                    // Move up the tree to the next parent.
                    current_symbol = enclosing_symbol.clone();
                }
            }
        }
    }

    // Third pass: extract function bodies from source files
    for node in call_graph.values_mut() {
        if !node.range.is_empty() {
            let file_path = &node.file_path;
            
            let clean_path = if file_path.starts_with("file://") {
                file_path.trim_start_matches("file://")
            } else {
                file_path
            };
            
            let abs_path = Path::new(clean_path);
            
            if let Ok(contents) = fs::read_to_string(abs_path) {
                let lines: Vec<&str> = contents.lines().collect();
                
                if node.range.len() >= 1 {
                    let start_line = node.range[0] as usize;
                    
                    if start_line < lines.len() {
                        let mut body_lines = Vec::new();
                        let mut open_braces = 0;
                        let mut found_first_brace = false;
                        
                        body_lines.push(lines[start_line]);
                        
                        for line_idx in start_line..lines.len() {
                            let line = lines[line_idx];
                            
                            if line_idx == start_line {
                                if line.contains('{') {
                                    found_first_brace = true;
                                    open_braces = line.matches('{').count().saturating_sub(line.matches('}').count());
                                }
                                continue;
                            }
                            
                            if !found_first_brace {
                                if line.contains('{') {
                                    found_first_brace = true;
                                    open_braces = line.matches('{').count().saturating_sub(line.matches('}').count());
                                }
                                body_lines.push(line);
                            } else {
                                open_braces += line.matches('{').count();
                                open_braces = open_braces.saturating_sub(line.matches('}').count());
                                body_lines.push(line);
                                if open_braces == 0 && found_first_brace {
                                    break;
                                }
                            }
                        }
                        
                        node.body = Some(body_lines.join("\n"));
                    }
                }
            } else {
                println!("Failed to read file for body extraction: {}", clean_path);
            }
        }
    }
    call_graph
}

/// Convert a SCIP symbol to a clean path format with display name
pub fn symbol_to_path(symbol: &str, display_name: &str) -> String {
    let mut parts = symbol.split_whitespace();
    let mut s = symbol;
    if parts.next() == Some("rust-analyzer") && parts.next() == Some("cargo") {
        if let Some(rest) = symbol.find("cargo ").and_then(|pos| symbol.get(pos + 6..)) {
            s = rest;
        }
    }
    
    if let Some(pos) = s.find(|c: char| c.is_digit(10)) {
        if let Some(space_pos) = s[pos..].find(' ') {
            s = s[(pos + space_pos + 1)..].trim();
        }
    }
    
    let mut clean_path = s
        .trim_end_matches('.')
        .replace('-', "_")
        .replace('[', "/")
        .replace(']', "/")
        .replace('#', "/")
        .trim_end_matches('/')
        .replace(&['`', '(', ')', '[', ']'][..], "")
        .replace("//", "/");

    let re = Regex::new(r"<[^>]*>").unwrap();
    clean_path = re.replace_all(&clean_path, "").to_string();
    if !clean_path.ends_with(display_name) {
        clean_path = format!("{}/{}", clean_path, display_name)
    }
    if clean_path.len() > 128 {
        clean_path.truncate(128);
    }
    clean_path
}

/// Write the call graph as a JSON array of Atom objects
pub fn write_call_graph_as_atoms_json<P: AsRef<std::path::Path>>(
    call_graph: &HashMap<String, FunctionNode>,
    output_path: P,
) -> std::io::Result<()> {
    let atoms: Vec<Atom> = call_graph.values().map(|node| {
        let body_content = node.body.clone().unwrap_or_else(|| "".to_string());

        // --- THIS IS THE FIX ---
        // Create a Path object from the clean relative_path.
        let rel_path = Path::new(&node.relative_path);

        // Derive file_name and parent_folder from the reliable relative_path.
        let file_name = rel_path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();

        let parent_folder = rel_path
            .parent()
            .and_then(|p| p.file_name()) // Get the direct parent folder name
            .and_then(|name| name.to_str())
            .unwrap_or_else(|| {
                // Handle root files which might not have a parent component in their relative path
                rel_path.parent()
                        .and_then(|p| p.to_str())
                        .filter(|s| !s.is_empty())
                        .unwrap_or("root")
            })
            .to_string();

        Atom {
            identifier: symbol_to_path(&node.symbol, &node.display_name),
            statement_type: "function".to_string(),
            deps: node.callees.iter()
                .filter_map(|callee| call_graph.get(callee))
                .map(|callee_node| symbol_to_path(&callee_node.symbol, &callee_node.display_name))
                .collect(),
            body: body_content,
            display_name: node.display_name.clone(),
            full_path: node.file_path.clone(), // Keep the full URI path here
            relative_path: node.relative_path.clone(), // Keep the clean relative path here
            file_name, // Use the correctly derived file name
            parent_folder, // Use the correctly derived parent folder
        }
    }).collect();

    let json = serde_json::to_string_pretty(&atoms).unwrap();
    std::fs::write(output_path, json)
}

/// Write the call graph as a JSON array of Atom objects
pub fn old_write_call_graph_as_atoms_json<P: AsRef<std::path::Path>>(
    call_graph: &HashMap<String, FunctionNode>,
    output_path: P,
) -> std::io::Result<()> {
    let atoms: Vec<Atom> = call_graph.values().map(|node| {
        let body_content = node.body.clone().unwrap_or_else(|| "".to_string());
        
        let parent_folder = Path::new(&node.file_path)
            .parent()
            .and_then(|p| p.file_name())
            .and_then(|name| name.to_str())
            .unwrap_or("unknown")
            .to_string();
        
        Atom {
            identifier: symbol_to_path(&node.symbol, &node.display_name),
            statement_type: "function".to_string(),
            deps: node.callees.iter()
                .filter_map(|callee| call_graph.get(callee))
                .map(|callee_node| symbol_to_path(&callee_node.symbol, &callee_node.display_name))
                .collect(),
            body: body_content,
            display_name: node.display_name.clone(),
            full_path: node.file_path.clone(),
            relative_path: node.relative_path.clone(),
            file_name: Path::new(&node.file_path)
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string(),
            parent_folder,
        }
    }).collect();
  
    let json = serde_json::to_string_pretty(&atoms).unwrap();
    std::fs::write(output_path, json)
}

/// Check if a symbol kind represents a function-like entity
fn is_function_like(kind: i32) -> bool {
    // According to SCIP spec: Method=6, Function=17, Constructor=26, Macro=80
    matches!(kind, 6 | 17 | 26 | 80)
}


//=========================================================
// All DOT generation functions remain unchanged below this line
//=========================================================

/// Generate a DOT file format for the call graph that can be rendered by Graphviz
pub fn generate_call_graph_dot(call_graph: &HashMap<String, FunctionNode>, output_path: &str) -> std::io::Result<()> {
    use std::collections::BTreeMap;
    let mut dot = String::from("digraph call_graph {\n");
    dot.push_str("  rankdir=LR;\n");
    dot.push_str("  node [shape=box, style=filled, fillcolor=lightblue, fontname=Helvetica];\n");
    dot.push_str("  edge [color=gray];\n\n");

    let skip_paths = [
        "libsignal/rust/protocol/benches",
        "libsignal/rust/protocol/tests",
        "libsignal/rust/protocol/examples",
    ];
    let filtered_nodes: Vec<&FunctionNode> = call_graph.values()
        .filter(|node| !skip_paths.iter().any(|p| node.file_path.contains(p)))
        .collect();

    let mut module_groups: BTreeMap<String, Vec<&FunctionNode>> = BTreeMap::new();
    for node in &filtered_nodes {
        let path = std::path::Path::new(&node.file_path);
        let module = path.parent().map(|p| p.display().to_string()).unwrap_or_else(|| "root".to_string());
        module_groups.entry(module).or_default().push(*node);
    }

    let mut cluster_id = 0;
    for (module, nodes) in &module_groups {
        dot.push_str(&format!("  subgraph cluster_{} {{\n    label = \"{}\";\n    style=filled;\n    color=lightgrey;\n    fontname=Helvetica;\n", cluster_id, module));
        for node in nodes {
            let label = node.display_name.clone();
            let tooltip = if let Some(body) = &node.body {
                let plain = body.replace('\n', " ").replace('\r', " ").replace('"', "' ");
                if plain.len() > 200 {
                    format!("{}...", &plain[..200])
                } else {
                    plain
                }
            } else {
                "".to_string()
            };
            dot.push_str(&format!(
                "    \"{}\" [label=\"{}\", tooltip=\"{}\"]\n",
                node.symbol, label, tooltip
            ));
        }
        dot.push_str("  }\n");
        cluster_id += 1;
    }

    dot.push_str("\n");

    let filtered_symbols: std::collections::HashSet<_> = filtered_nodes.iter().map(|n| &n.symbol).collect();
    for node in &filtered_nodes {
        for callee in &node.callees {
            if filtered_symbols.contains(callee) {
                dot.push_str(&format!("  \"{}\" -> \"{}\"\n", node.symbol, callee));
            }
        }
    }

    dot.push_str("}\n");
    std::fs::write(output_path, dot)
}

/// Generate a DOT file format for a subgraph of the call graph containing only nodes from a specific file path
pub fn generate_file_subgraph_dot(
    call_graph: &HashMap<String, FunctionNode>, 
    file_path: &str, 
    output_path: &str
) -> std::io::Result<()> {
    use std::collections::HashSet;
    let mut dot = String::from("digraph file_subgraph {\n");
    dot.push_str("  rankdir=LR;\n");
    dot.push_str("  node [shape=box, style=filled, fontname=Helvetica];\n");
    dot.push_str("  edge [color=gray];\n\n");

    // Find nodes that belong to the specified file - more flexible path matching
    let file_nodes: Vec<&FunctionNode> = call_graph.values()
        .filter(|node| {
            // Extract the filename from the provided file_path argument
            let requested_filename = Path::new(file_path)
            .file_name()
            .and_then(|f| f.to_str())
            .unwrap_or(file_path);
            node.file_path.ends_with(file_path)
            || node.file_path == file_path
            || node.symbol.contains(file_path)
            || node.file_path.contains(requested_filename)
        })
        .collect();
    
    if file_nodes.is_empty() {
        // List available paths that contain part of the requested path
        let matching_paths: HashSet<_> = call_graph.values()
            .filter(|node| node.file_path.contains(file_path))
            .map(|node| &node.file_path)
            .collect();
        
        if !matching_paths.is_empty() {
            let mut message = format!("No exact match for file path: {}\n\nHere are some similar paths:\n", file_path);
            for path in matching_paths {
                message.push_str(&format!("  {}\n", path));
            }
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                message
            ));
        }
        
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("No functions found in file path: {}", file_path)
        ));
    }
    
    println!("Found {} functions in file {}", file_nodes.len(), file_path);
    for node in &file_nodes {
        println!("  - {} ({})", node.display_name, node.symbol);
    }
    
    // Get the symbols of nodes in the file
    let file_symbols: HashSet<String> = file_nodes.iter().map(|n| n.symbol.clone()).collect();
    
    // Nodes that are called by or call into nodes from this file (1st degree connections)
    let mut connected_symbols = HashSet::new();
    for node in &file_nodes {
        // Add callees
        for callee in &node.callees {
            connected_symbols.insert(callee.clone());
        }
        // Add callers
        for caller in &node.callers {
            connected_symbols.insert(caller.clone());
        }
    }
    
    // Draw file nodes with blue background
    for node in &file_nodes {
        let label = node.display_name.clone();
        let tooltip = if let Some(body) = &node.body {
            let plain = body.replace('\n', " ").replace('\r', " ").replace('"', "' ");
            if plain.len() > 200 {
                format!("{}...", &plain[..200])
            } else {
                plain
            }
        } else {
            "".to_string()
        };
        dot.push_str(&format!(
            "  \"{}\" [label=\"{}\", tooltip=\"{}\", fillcolor=lightblue]\n",
            node.symbol, label, tooltip
        ));
    }
    
    // Draw connected nodes with light gray background
    for symbol in &connected_symbols {
        if !file_symbols.contains(symbol) {
            if let Some(node) = call_graph.get(symbol) {
                let label = node.display_name.clone();
                dot.push_str(&format!(
                    "  \"{}\" [label=\"{}\", fillcolor=lightgray]\n",
                    node.symbol, label
                ));
            }
        }
    }
    
    dot.push_str("\n");
    
    // Draw edges from file nodes to their callees
    for node in &file_nodes {
        for callee in &node.callees {
            if file_symbols.contains(callee) || connected_symbols.contains(callee) {
                dot.push_str(&format!("  \"{}\" -> \"{}\"\n", node.symbol, callee));
            }
        }
    }
    
    // Draw edges from callers to file nodes
    for node in &file_nodes {
        for caller in &node.callers {
            if !file_symbols.contains(caller) && connected_symbols.contains(caller) {
                dot.push_str(&format!("  \"{}\" -> \"{}\"\n", caller, node.symbol));
            }
        }
    }
    
    dot.push_str("}\n");
    std::fs::write(output_path, dot)
}

/// Generate a DOT file format for a subgraph of the call graph containing only nodes from a specific set of file paths
pub fn generate_files_subgraph_dot(
    call_graph: &HashMap<String, FunctionNode>, 
    file_paths: &[String], 
    output_path: &str
) -> std::io::Result<()> {
    use std::collections::{BTreeMap, HashSet};
    let mut dot = String::from("digraph files_subgraph {\n");
    dot.push_str("  rankdir=LR;\n");
    dot.push_str("  node [shape=box, style=filled, fontname=Helvetica];\n");
    dot.push_str("  edge [color=gray];\n\n");

    // Helper function for file path matching
    fn is_file_match(node_path: &str, requested_paths: &[String]) -> bool {
        for path in requested_paths {
            // Extract the filename from the provided file_path
            let requested_filename = Path::new(path)
                .file_name()
                .and_then(|f| f.to_str())
                .unwrap_or(path);
                
            if node_path.ends_with(path)
                || node_path == path
                || node_path.contains(requested_filename) {
                return true;
            }
        }
        false
    }

    // Find nodes that belong to any of the specified files
    let file_nodes: Vec<&FunctionNode> = call_graph.values()
        .filter(|node| is_file_match(&node.file_path, file_paths))
        .collect();
    
    if file_nodes.is_empty() {
        // List available paths that contain part of the requested paths
        let mut matching_paths: HashSet<&String> = HashSet::new();
        for path in file_paths {
            for node in call_graph.values() {
                if node.file_path.contains(path) {
                    matching_paths.insert(&node.file_path);
                }
            }
        }
        
        if !matching_paths.is_empty() {
            let mut message = format!("No exact matches for file paths: {:?}\n\nHere are some similar paths:\n", file_paths);
            for path in matching_paths {
                message.push_str(&format!("  {}\n", path));
            }
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                message
            ));
        }
        
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("No functions found in file paths: {:?}", file_paths)
        ));
    }
    
    println!("Found {} functions in the specified files", file_nodes.len());
    
    // Get the symbols of nodes in the files
    let file_symbols: HashSet<String> = file_nodes.iter().map(|n| n.symbol.clone()).collect();
    
    // Nodes that are called by or call into nodes from these files (1st degree connections)
    let mut connected_symbols = HashSet::new();
    for node in &file_nodes {
        // Add callees
        for callee in &node.callees {
            connected_symbols.insert(callee.clone());
        }
        // Add callers
        for caller in &node.callers {
            connected_symbols.insert(caller.clone());
        }
    }
    
    // Group file nodes by their file path for subgraph clustering
    let mut file_groups: BTreeMap<String, Vec<&FunctionNode>> = BTreeMap::new();
    for node in &file_nodes {
        file_groups.entry(node.file_path.clone()).or_default().push(node);
    }
    
    // Draw clusters for each file with blue background nodes
    let mut cluster_id = 0;
    for (file_path, nodes) in &file_groups {
        let file_label = Path::new(file_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("unknown");
            
        dot.push_str(&format!("  subgraph cluster_{} {{\n", cluster_id));
        dot.push_str(&format!("    label = \"{}\";\n", file_label));
        dot.push_str("    style=filled;\n");
        dot.push_str("    color=lightblue;\n");
        dot.push_str("    fontname=Helvetica;\n");
        
        for node in nodes {
            let label = node.display_name.clone();
            let tooltip = if let Some(body) = &node.body {
                let plain = body.replace('\n', " ").replace('\r', " ").replace('"', "' ");
                if plain.len() > 200 {
                    format!("{}...", &plain[..200])
                } else {
                    plain
                }
            } else {
                "".to_string()
            };
            dot.push_str(&format!(
                "    \"{}\" [label=\"{}\", tooltip=\"{}\", fillcolor=white]\n",
                node.symbol, label, tooltip
            ));
        }
        
        dot.push_str("  }\n");
        cluster_id += 1;
    }
    
    // Draw connected nodes with light gray background
    for symbol in &connected_symbols {
        if !file_symbols.contains(symbol) {
            if let Some(node) = call_graph.get(symbol) {
                let label = node.display_name.clone();
                dot.push_str(&format!(
                    "  \"{}\" [label=\"{}\", fillcolor=lightgray]\n",
                    node.symbol, label
                ));
            }
        }
    }
    
    dot.push_str("\n");
    
    // Draw edges
    // From file nodes to their callees
    for node in &file_nodes {
        for callee in &node.callees {
            if file_symbols.contains(callee) || connected_symbols.contains(callee) {
                dot.push_str(&format!("  \"{}\" -> \"{}\"\n", node.symbol, callee));
            }
        }
    }
    
    // From callers to file nodes
    for node in &file_nodes {
        for caller in &node.callers {
            if !file_symbols.contains(caller) && connected_symbols.contains(caller) {
                dot.push_str(&format!("  \"{}\" -> \"{}\"\n", caller, node.symbol));
            }
        }
    }
    
    dot.push_str("}\n");
    std::fs::write(output_path, dot)
}

/// Generate a DOT file format for a subgraph of the call graph containing only specified functions and their transitive dependencies
pub fn generate_function_subgraph_dot(
    call_graph: &HashMap<String, FunctionNode>, 
    function_names: &[String], 
    output_path: &str,
    include_callers: bool
) -> std::io::Result<()> {
    use std::collections::{BTreeMap, HashSet, VecDeque};
    let mut dot = String::from("digraph function_subgraph {\n");
    dot.push_str("  rankdir=LR;\n");
    dot.push_str("  node [shape=box, style=filled, fontname=Helvetica];\n");
    dot.push_str("  edge [color=gray];\n\n");

    // Find nodes that match the specified function names
    let mut matched_nodes = Vec::new();
    let mut matched_symbols = HashSet::new();
    
    // Helper function to match function names to nodes
    for function_name in function_names {
        let matches: Vec<_> = call_graph.values()
            .filter(|node| 
                node.display_name == *function_name || 
                node.symbol.contains(function_name) ||
                symbol_to_path(&node.symbol, &node.display_name).contains(function_name)
            )
            .collect();
        
        for node in matches {
            matched_nodes.push(node);
            matched_symbols.insert(node.symbol.clone());
        }
    }
    
    if matched_nodes.is_empty() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("No functions found matching the provided names: {:?}", function_names)
        ));
    }
    
    println!("Found {} functions matching the provided names", matched_nodes.len());
    for node in &matched_nodes {
        println!("  - {} ({})", node.display_name, node.symbol);
    }
    
    // Build the transitive closure of dependencies
    let mut included_symbols = matched_symbols.clone();
    let mut queue = VecDeque::new();
    for symbol in &matched_symbols {
        queue.push_back(symbol.clone());
    }
    
    // BFS to find all transitive dependencies
    while let Some(symbol) = queue.pop_front() {
        if let Some(node) = call_graph.get(&symbol) {
            // Add callees (dependencies)
            for callee in &node.callees {
                if !included_symbols.contains(callee) {
                    included_symbols.insert(callee.clone());
                    queue.push_back(callee.clone());
                }
            }
            
            // Optionally include callers as well
            if include_callers {
                for caller in &node.callers {
                    if !included_symbols.contains(caller) {
                        included_symbols.insert(caller.clone());
                        queue.push_back(caller.clone());
                    }
                }
            }
        }
    }
    
    // Group nodes by file path for visual organization
    let mut file_groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for symbol in &included_symbols {
        if let Some(node) = call_graph.get(symbol) {
            file_groups.entry(node.file_path.clone()).or_default().push(symbol.clone());
        }
    }
    
    // Create clusters for each file
    let mut cluster_id = 0;
    for (file_path, symbols) in &file_groups {
        let file_label = Path::new(file_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("unknown");
            
        dot.push_str(&format!("  subgraph cluster_{} {{\n", cluster_id));
        dot.push_str(&format!("    label = \"{}\";\n", file_label));
        dot.push_str("    style=filled;\n");
        dot.push_str("    color=lightgrey;\n");
        dot.push_str("    fontname=Helvetica;\n");
        
        for symbol in symbols {
            if let Some(node) = call_graph.get(symbol) {
                let label = node.display_name.clone();
                let tooltip = if let Some(body) = &node.body {
                    let plain = body.replace('\n', " ").replace('\r', " ").replace('"', "' ");
                    if plain.len() > 200 {
                        format!("{}...", &plain[..200])
                    } else {
                        plain
                    }
                } else {
                    "".to_string()
                };
                
                // Color the initially matched nodes differently
                let fillcolor = if matched_symbols.contains(symbol) {
                    "lightblue"
                } else {
                    "white"
                };
                
                dot.push_str(&format!(
                    "    \"{}\" [label=\"{}\", tooltip=\"{}\", fillcolor={}]\n",
                    node.symbol, label, tooltip, fillcolor
                ));
            }
        }
        
        dot.push_str("  }\n");
        cluster_id += 1;
    }
    
    dot.push_str("\n");
    
    // Draw edges between all included nodes
    for symbol in &included_symbols {
        if let Some(node) = call_graph.get(symbol) {
            for callee in &node.callees {
                if included_symbols.contains(callee) {
                    dot.push_str(&format!("  \"{}\" -> \"{}\"\n", node.symbol, callee));
                }
            }
        }
    }
    
    dot.push_str("}\n");
    std::fs::write(output_path, dot)
}

pub fn generate_call_graph_svg(call_graph: &HashMap<String, FunctionNode>, output_path: &str) -> std::io::Result<()> {
    let node_radius = 40;
    let width = 1200;
    let height = 800;
    let mut svg = format!(
        r#"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' style='background:#fff;font-family:sans-serif'>\n"#,
        w=width, h=height
    );

    // Use a force-directed layout instead of circular
    // This is a simple implementation - for complex graphs, use a dot file with Graphviz
    let nodes: Vec<_> = call_graph.values().collect();
    let _n = nodes.len();
    
    // Initial random positions
    let mut positions = HashMap::new();
    let mut rng = std::hash::DefaultHasher::new();
    for node in &nodes {
        use std::hash::{Hash, Hasher};
        node.symbol.hash(&mut rng);
        let x = (rng.finish() % 800) as f64 + 200.0;
        rng.write_u8(1);
        let y = (rng.finish() % 600) as f64 + 100.0;
        positions.insert(&node.symbol, (x, y));
    }

    // Arrows marker definition
    svg.push_str("<defs><marker id='arrow' markerWidth='10' markerHeight='10' refX='10' refY='5' orient='auto' markerUnits='strokeWidth'><path d='M0,0 L10,5 L0,10 z' fill='#888'/></marker></defs>\n");

    // Draw edges
    for node in call_graph.values() {
        let (x1, y1) = positions[&node.symbol];
        for callee in &node.callees {
            if let Some(&(x2, y2)) = positions.get(callee) {
                svg.push_str(&format!(
                    "<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='#888' stroke-width='2' marker-end='url(#arrow)'/>\n",
                    x1=x1, y1=y1, x2=x2, y2=y2
                ));
            }
        }
    }

    // Draw nodes
    for node in call_graph.values() {
        let (x, y) = positions[&node.symbol];
        let body = node.body.as_ref().map(|b| html_escape::encode_safe(b)).unwrap_or_default();
        svg.push_str(&format!(
            "<g>\
                <circle cx='{x}' cy='{y}' r='{r}' fill='#4a90e2' stroke='#222' stroke-width='2'/>\
                <text x='{x}' y='{y}' text-anchor='middle' alignment-baseline='middle' fill='#fff' font-size='14'>{label}</text>\
                <title>{body}</title>\
            </g>\n",
            x=x, y=y, r=node_radius, label=html_escape::encode_safe(&node.display_name), body=body
        ));
    }

    svg.push_str("</svg>\n");
    fs::write(output_path, svg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::fs;
    use tempfile::NamedTempFile;
    use regex::Regex;

    // The previous tests referred to svg content in tooltips which is not in the code
    // Replacing with a more relevant test
    #[test]
    fn test_function_body_extraction() {
        let mut call_graph = HashMap::new();
        call_graph.insert("f1".to_string(), FunctionNode {
            symbol: "f1".to_string(),
            display_name: "foo".to_string(),
            file_path: "/tmp/foo.rs".to_string(),
            relative_path: "tmp/foo.rs".to_string(),
            callers: HashSet::new(),
            callees: HashSet::new(),
            range: vec![],
            body: Some("fn foo() { println!(\"Hello\"); }".to_string()),
        });
        let tmp = NamedTempFile::new().unwrap();
        generate_call_graph_dot(&call_graph, tmp.path().to_str().unwrap()).unwrap();
        let dot = fs::read_to_string(tmp.path()).unwrap();
        assert!(dot.contains("tooltip=\"fn foo() { println!(\\\"Hello\\\"); }\""));
    }
}


// ... (The rest of your DOT generation functions can be pasted here without any changes)
// generate_file_subgraph_dot
// generate_files_subgraph_dot
// generate_function_subgraph_dot
// generate_call_graph_svg
// etc.
