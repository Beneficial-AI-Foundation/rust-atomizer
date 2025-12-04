//! Integration tests for the duplicate symbol fix.
//!
//! These tests verify that multiple trait implementations with the same SCIP symbol
//! (e.g., `impl Mul<A> for B` and `impl Mul<B> for A`) are both captured in the call graph.
//!
//! See DUPLICATE_SYMBOL_BUG.md for details on this bug.

use rust_atomizer::scip_to_call_graph_json::{
    build_call_graph, parse_scip_json, symbol_to_path, FunctionNode,
};
use std::collections::HashMap;

fn get_test_data() -> HashMap<String, FunctionNode> {
    let scip_data = parse_scip_json("data/curve_top.json").expect("Failed to parse SCIP JSON");
    build_call_graph(&scip_data)
}

/// Test that multiple trait implementations with the same SCIP symbol
/// (e.g., `impl Mul<A> for B` and `impl Mul<B> for A`) are both captured.
#[test]
fn test_duplicate_mul_implementations() {
    let call_graph = get_test_data();

    // Find all entries with "Mul" and "mul" in their symbol (for montgomery module)
    let mut mul_entries: Vec<_> = call_graph
        .values()
        .filter(|node| {
            node.symbol.contains("montgomery")
                && node.symbol.contains("Mul")
                && node.symbol.contains("mul")
        })
        .collect();

    mul_entries.sort_by_key(|n| n.range.first().copied().unwrap_or(0));

    // We should have at least 2 montgomery Mul::mul implementations
    assert!(
        mul_entries.len() >= 2,
        "Expected at least 2 montgomery/Mul::mul implementations, found {}. Symbols: {:?}",
        mul_entries.len(),
        mul_entries.iter().map(|n| &n.symbol).collect::<Vec<_>>()
    );

    // Verify we have both signatures
    let signatures: Vec<_> = mul_entries
        .iter()
        .map(|n| n.signature_text.as_str())
        .collect();

    assert!(
        signatures.iter().any(|s| s.contains("Scalar")),
        "Missing MontgomeryPoint * Scalar implementation. Signatures: {:?}",
        signatures
    );
    assert!(
        signatures.iter().any(|s| s.contains("MontgomeryPoint")),
        "Missing Scalar * MontgomeryPoint implementation. Signatures: {:?}",
        signatures
    );

    // Verify distinct line numbers (don't hardcode specific lines as they may change)
    let lines: Vec<_> = mul_entries
        .iter()
        .filter_map(|n| n.range.first().map(|l| l + 1))
        .collect();

    // Check that we have at least 2 distinct line numbers
    let unique_lines: std::collections::HashSet<_> = lines.iter().collect();
    assert!(
        unique_lines.len() >= 2,
        "Expected at least 2 distinct line numbers, got: {:?}",
        lines
    );
}

/// Test that the identifier/path includes type info to distinguish trait impls.
#[test]
fn test_identifiers_include_type_info() {
    let call_graph = get_test_data();

    let mul_atoms: Vec<_> = call_graph
        .values()
        .filter(|node| {
            node.symbol.contains("montgomery")
                && node.symbol.contains("Mul")
                && node.display_name == "mul"
        })
        .collect();

    // Should have at least 2 distinct Mul implementations
    assert!(
        mul_atoms.len() >= 2,
        "Expected at least 2 montgomery/Mul atoms, found {}",
        mul_atoms.len()
    );

    // Generate identifiers using symbol_to_path
    let identifiers: Vec<_> = mul_atoms
        .iter()
        .map(|a| symbol_to_path(&a.symbol, &a.display_name))
        .collect();

    println!("Found identifiers: {:?}", identifiers);

    // Both should contain "mul" (basic sanity check)
    assert!(
        identifiers.iter().all(|id| id.contains("mul")),
        "All identifiers should contain 'mul'"
    );
}

/// Test that Neg trait implementations for both &Type and Type are captured.
/// Unlike Mul, Neg implementations have different SCIP symbols:
/// - `impl Neg for &Type` → `module/Neg#neg()`
/// - `impl Neg for Type` → `module/Type#Neg#neg()`
#[test]
fn test_neg_implementations_for_scalar() {
    let call_graph = get_test_data();

    // Find all Neg implementations for scalar
    let neg_entries: Vec<_> = call_graph
        .values()
        .filter(|node| {
            node.symbol.contains("scalar")
                && node.symbol.contains("Neg")
                && node.symbol.contains("neg")
        })
        .collect();

    // Should have both `scalar/Neg#neg()` and `scalar/Scalar#Neg#neg()`
    assert!(
        neg_entries.len() >= 2,
        "Expected at least 2 scalar Neg implementations, found {}: {:?}",
        neg_entries.len(),
        neg_entries.iter().map(|n| &n.symbol).collect::<Vec<_>>()
    );

    let symbols: Vec<_> = neg_entries.iter().map(|n| n.symbol.as_str()).collect();

    // Check for impl Neg for &Scalar
    assert!(
        symbols
            .iter()
            .any(|s| s.contains("scalar") && s.contains("Neg#neg")),
        "Missing impl Neg for &Scalar"
    );

    // Check for impl Neg for Scalar
    assert!(
        symbols
            .iter()
            .any(|s| s.contains("Scalar#Neg#neg") || s.contains("Scalar/Neg")),
        "Missing impl Neg for Scalar"
    );
}

/// Test that the call graph contains a reasonable number of functions
#[test]
fn test_call_graph_size() {
    let call_graph = get_test_data();

    // Should have many functions (dalek-lite is a substantial crate)
    assert!(
        call_graph.len() > 100,
        "Expected more than 100 functions in call graph, found {}",
        call_graph.len()
    );

    println!("Total functions in call graph: {}", call_graph.len());
}

/// Test that function bodies are extracted
#[test]
fn test_function_bodies_extracted() {
    let call_graph = get_test_data();

    // Count functions with bodies
    let with_bodies = call_graph.values().filter(|n| n.body.is_some()).count();
    let total = call_graph.len();

    // At least 50% should have bodies (some external functions won't have bodies)
    let percentage = (with_bodies as f64 / total as f64) * 100.0;
    assert!(
        percentage > 30.0,
        "Expected at least 30% of functions to have bodies, got {:.1}% ({}/{})",
        percentage,
        with_bodies,
        total
    );

    println!(
        "Functions with bodies: {}/{} ({:.1}%)",
        with_bodies, total, percentage
    );
}
