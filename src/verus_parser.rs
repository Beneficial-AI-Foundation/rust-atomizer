//! Verus-aware source file parser using verus_syn
//!
//! This module provides accurate function span extraction for Verus source files.
//! It handles all Verus-specific syntax including:
//! - `verus!` macro contents
//! - `requires`, `ensures`, `decreases` clauses
//! - `forall`, `exists` quantifiers
//! - `==>` implications, `&&&`, `|||` operators
//!
//! This is much more reliable than brace-counting for extracting function bodies.

use log::debug;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use verus_syn::{parse_file, parse2, File, ImplItem, Item};
use verus_syn::spanned::Spanned;

/// Represents a function's location in a source file
#[derive(Debug, Clone)]
pub struct FunctionSpan {
    pub name: String,
    pub start_line: usize,  // 1-indexed
    pub end_line: usize,    // 1-indexed (inclusive)
}

/// Parse a Verus/Rust source file and extract all function spans
pub fn extract_function_spans(file_path: &str) -> Result<Vec<FunctionSpan>, String> {
    let path = Path::new(file_path);
    let content = fs::read_to_string(path)
        .map_err(|e| format!("Failed to read file {}: {}", file_path, e))?;

    extract_function_spans_from_content(&content)
}

/// Parse content string and extract all function spans
pub fn extract_function_spans_from_content(content: &str) -> Result<Vec<FunctionSpan>, String> {
    let file = parse_file(content)
        .map_err(|e| format!("Failed to parse file: {}", e))?;

    let mut spans = Vec::new();
    extract_from_items(&file.items, &mut spans);
    Ok(spans)
}

/// Recursively extract function spans from items
fn extract_from_items(items: &[Item], spans: &mut Vec<FunctionSpan>) {
    for item in items {
        match item {
            Item::Fn(func) => {
                let name = func.sig.ident.to_string();
                let span = func.span();
                let start = span.start();
                let end = span.end();
                spans.push(FunctionSpan {
                    name,
                    start_line: start.line,
                    end_line: end.line,
                });
            }
            Item::Impl(impl_block) => {
                for impl_item in &impl_block.items {
                    if let ImplItem::Fn(method) = impl_item {
                        let name = method.sig.ident.to_string();
                        let span = method.span();
                        let start = span.start();
                        let end = span.end();
                        spans.push(FunctionSpan {
                            name,
                            start_line: start.line,
                            end_line: end.line,
                        });
                    }
                }
            }
            Item::Mod(module) => {
                if let Some((_, items)) = &module.content {
                    extract_from_items(items, spans);
                }
            }
            Item::Macro(mac) => {
                // Parse contents of verus! macros
                if mac.mac.path.is_ident("verus") {
                    let tokens = mac.mac.tokens.clone();
                    
                    if let Ok(inner_file) = parse2::<File>(tokens) {
                        // Extract functions from inside the verus! macro
                        // Note: spans inside the macro are relative to macro start
                        let mut inner_spans = Vec::new();
                        extract_from_items(&inner_file.items, &mut inner_spans);
                        
                        // The spans from parse2 are relative to the token stream,
                        // but verus_syn preserves the original spans, so we can use them directly
                        spans.extend(inner_spans);
                    }
                }
            }
            _ => {}
        }
    }
}

/// Build a map from function name to its span for quick lookups
/// Note: If there are multiple functions with the same name, all are included
pub fn build_function_span_map(file_path: &str) -> Result<HashMap<String, Vec<FunctionSpan>>, String> {
    let spans = extract_function_spans(file_path)?;
    let mut map: HashMap<String, Vec<FunctionSpan>> = HashMap::new();
    
    for span in spans {
        map.entry(span.name.clone()).or_default().push(span);
    }
    
    Ok(map)
}

/// Extract a function body given the file content and span
pub fn extract_body_from_span(content: &str, span: &FunctionSpan) -> String {
    let lines: Vec<&str> = content.lines().collect();
    
    if span.start_line == 0 || span.end_line == 0 {
        return String::new();
    }
    
    // Convert to 0-indexed
    let start_idx = span.start_line.saturating_sub(1);
    let end_idx = span.end_line.min(lines.len());
    
    if start_idx >= lines.len() {
        return String::new();
    }
    
    lines[start_idx..end_idx].join("\n")
}

/// Find the best matching function span for a given function name and approximate line number
/// This is useful when matching SCIP occurrences to verus_syn spans
pub fn find_best_match<'a>(
    spans: &'a [FunctionSpan],
    name: &str,
    approx_line: usize,
) -> Option<&'a FunctionSpan> {
    let matching: Vec<_> = spans.iter()
        .filter(|s| s.name == name)
        .collect();
    
    if matching.is_empty() {
        return None;
    }
    
    if matching.len() == 1 {
        return Some(matching[0]);
    }
    
    // Multiple matches - find the one closest to the approximate line
    matching.into_iter()
        .min_by_key(|s| (s.start_line as i64 - approx_line as i64).abs())
}

/// Cache for parsed files to avoid re-parsing
pub struct FileSpanCache {
    cache: HashMap<String, Vec<FunctionSpan>>,
}

impl FileSpanCache {
    pub fn new() -> Self {
        Self {
            cache: HashMap::new(),
        }
    }

    /// Get function spans for a file, parsing it if not already cached
    pub fn get_spans(&mut self, file_path: &str) -> Result<&Vec<FunctionSpan>, String> {
        if !self.cache.contains_key(file_path) {
            debug!("Parsing file with verus_syn: {}", file_path);
            let spans = extract_function_spans(file_path)?;
            debug!("Found {} functions in {}", spans.len(), file_path);
            self.cache.insert(file_path.to_string(), spans);
        }
        Ok(self.cache.get(file_path).unwrap())
    }

    /// Find a function body given file path, function name, and approximate line
    pub fn get_function_body(
        &mut self,
        file_path: &str,
        function_name: &str,
        approx_line: usize,
    ) -> Result<Option<String>, String> {
        let spans = self.get_spans(file_path)?;
        
        if let Some(span) = find_best_match(spans, function_name, approx_line) {
            let content = fs::read_to_string(file_path)
                .map_err(|e| format!("Failed to read file {}: {}", file_path, e))?;
            Ok(Some(extract_body_from_span(&content, span)))
        } else {
            Ok(None)
        }
    }
}

impl Default for FileSpanCache {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_function() {
        let code = r#"
fn hello() {
    println!("Hello");
}
"#;
        let spans = extract_function_spans_from_content(code).unwrap();
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].name, "hello");
        assert_eq!(spans[0].start_line, 2);
        assert_eq!(spans[0].end_line, 4);
    }

    #[test]
    fn test_impl_block() {
        let code = r#"
struct Foo;

impl Foo {
    fn bar(&self) {
        todo!()
    }
    
    fn baz(&self) -> i32 {
        42
    }
}
"#;
        let spans = extract_function_spans_from_content(code).unwrap();
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0].name, "bar");
        assert_eq!(spans[1].name, "baz");
    }

    #[test]
    fn test_find_best_match() {
        let spans = vec![
            FunctionSpan { name: "foo".to_string(), start_line: 10, end_line: 20 },
            FunctionSpan { name: "foo".to_string(), start_line: 100, end_line: 110 },
            FunctionSpan { name: "bar".to_string(), start_line: 50, end_line: 60 },
        ];
        
        // Should find the foo closest to line 15
        let result = find_best_match(&spans, "foo", 15);
        assert!(result.is_some());
        assert_eq!(result.unwrap().start_line, 10);
        
        // Should find the foo closest to line 105
        let result = find_best_match(&spans, "foo", 105);
        assert!(result.is_some());
        assert_eq!(result.unwrap().start_line, 100);
        
        // Should find bar
        let result = find_best_match(&spans, "bar", 55);
        assert!(result.is_some());
        assert_eq!(result.unwrap().start_line, 50);
        
        // Should return None for non-existent function
        let result = find_best_match(&spans, "nonexistent", 50);
        assert!(result.is_none());
    }
}

