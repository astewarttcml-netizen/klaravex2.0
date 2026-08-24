//! Klaravex Customer Helper — library crate.
//!
//! The bin target (`klaravex-helper`) thin-wraps these modules. Exposing them
//! as a lib lets integration tests in `tests/` import the same code that the
//! bin runs, so the contract test in `tests/contract.rs` can call
//! `klaravex_customer_helper::token::redeem` without rebuilding the helper.

pub mod cleanup;
pub mod config;
pub mod indicator;
pub mod launcher;
pub mod token;
