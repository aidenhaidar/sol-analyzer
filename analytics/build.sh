#!/usr/bin/env bash
# Builds the analytics crate to WebAssembly and emits JS bindings into web/src/wasm.
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen --target web --out-dir ../web/src/wasm --out-name sol_analytics \
  target/wasm32-unknown-unknown/release/sol_analytics.wasm
echo "wasm written to web/src/wasm"
