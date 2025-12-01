//! Verus-aware source file parser using verus_syn
//!
//! This module provides accurate function span extraction for Verus source files.
//! It handles all Verus-specific syntax including:
//! - `verus!` macro contents
//! - `requires`, `ensures`, `decreases` clauses
//! - `forall`, `exists` quantifiers
//! - `==>` implications, `&&&`, `|||` operators
//!
//! Uses the visitor pattern for proper AST traversal.

use log::debug;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use verus_syn::spanned::Spanned;
use verus_syn::visit::Visit;
use verus_syn::{ImplItemFn, Item, ItemFn, ItemMacro, TraitItemFn};

/// Represents a function's location in a source file
#[derive(Debug, Clone)]
pub struct FunctionSpan {
    pub name: String,
    pub start_line: usize,  // 1-indexed
    pub end_line: usize,    // 1-indexed (inclusive)
}

/// Visitor that collects function spans from an AST
struct FunctionSpanVisitor {
    functions: Vec<FunctionSpan>,
}

impl FunctionSpanVisitor {
    fn new() -> Self {
        Self {
            functions: Vec::new(),
        }
    }
}

impl<'ast> Visit<'ast> for FunctionSpanVisitor {
    fn visit_item_fn(&mut self, node: &'ast ItemFn) {
        let name = node.sig.ident.to_string();
        let span = node.span();
        let start_line = span.start().line;
        let end_line = span.end().line;

        self.functions.push(FunctionSpan {
            name,
            start_line,
            end_line,
        });

        // Continue visiting nested items
        verus_syn::visit::visit_item_fn(self, node);
    }

    fn visit_impl_item_fn(&mut self, node: &'ast ImplItemFn) {
        let name = node.sig.ident.to_string();
        let span = node.span();
        let start_line = span.start().line;
        let end_line = span.end().line;

        self.functions.push(FunctionSpan {
            name,
            start_line,
            end_line,
        });

        // Continue visiting nested items
        verus_syn::visit::visit_impl_item_fn(self, node);
    }

    fn visit_trait_item_fn(&mut self, node: &'ast TraitItemFn) {
        let name = node.sig.ident.to_string();
        let span = node.span();
        let start_line = span.start().line;
        let end_line = span.end().line;

        self.functions.push(FunctionSpan {
            name,
            start_line,
            end_line,
        });

        // Continue visiting nested items
        verus_syn::visit::visit_trait_item_fn(self, node);
    }

    // Ensure we traverse into impl blocks
    fn visit_item_impl(&mut self, node: &'ast verus_syn::ItemImpl) {
        verus_syn::visit::visit_item_impl(self, node);
    }

    // Ensure we traverse into trait definitions
    fn visit_item_trait(&mut self, node: &'ast verus_syn::ItemTrait) {
        verus_syn::visit::visit_item_trait(self, node);
    }

    // Ensure we traverse into modules
    fn visit_item_mod(&mut self, node: &'ast verus_syn::ItemMod) {
        verus_syn::visit::visit_item_mod(self, node);
    }

    // Handle verus! macro blocks by parsing their contents
    fn visit_item_macro(&mut self, node: &'ast ItemMacro) {
        // Check if this is a verus! macro
        if let Some(ident) = &node.mac.path.get_ident() {
            if *ident == "verus" {
                // Try to parse the macro body as items
                if let Ok(items) = verus_syn::parse2::<VerusMacroBody>(node.mac.tokens.clone()) {
                    for item in items.items {
                        self.visit_item(&item);
                    }
                }
            }
        }
        // Continue with default traversal
        verus_syn::visit::visit_item_macro(self, node);
    }
}

/// Helper struct to parse verus! macro body as a list of items
struct VerusMacroBody {
    items: Vec<Item>,
}

impl verus_syn::parse::Parse for VerusMacroBody {
    fn parse(input: verus_syn::parse::ParseStream) -> verus_syn::Result<Self> {
        let mut items = Vec::new();
        while !input.is_empty() {
            items.push(input.parse()?);
        }
        Ok(VerusMacroBody { items })
    }
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
    let syntax_tree = verus_syn::parse_file(content)
        .map_err(|e| format!("Failed to parse file: {}", e))?;

    let mut visitor = FunctionSpanVisitor::new();
    visitor.visit_file(&syntax_tree);

    Ok(visitor.functions)
}

/// Find the best matching function span for a given function name and approximate line number.
/// 
/// Uses fuzzy matching with tolerance to account for doc comments which are included
/// in the function's span by the parser, but SCIP points to the signature line.
pub fn find_best_match<'a>(
    spans: &'a [FunctionSpan],
    name: &str,
    approx_line: usize,
) -> Option<&'a FunctionSpan> {
    // Tolerance for fuzzy matching - accounts for doc comments
    const TOLERANCE: usize = 15;
    
    // First try exact name match
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
    // First try exact match
    for span in &matching {
        if span.start_line == approx_line {
            return Some(span);
        }
    }
    
    // Then try within tolerance
    for span in &matching {
        let diff = if span.start_line > approx_line {
            span.start_line - approx_line
        } else {
            approx_line - span.start_line
        };
        
        if diff <= TOLERANCE {
            return Some(span);
        }
    }
    
    // Fallback: return the closest one
    matching.into_iter()
        .min_by_key(|s| (s.start_line as i64 - approx_line as i64).abs())
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
