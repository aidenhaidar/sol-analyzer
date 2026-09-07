//! HTTP + WebSocket API.
//!   GET  /health
//!   GET  /watch                      -> watched mints
//!   POST /watch/{mint}               -> start tracking (resubscribes the source)
//!   DELETE /watch/{mint}
//!   GET  /state/{mint}?top=50        -> snapshot incl. recent slot history
//!   GET  /holders/{mint}             -> full holder list [(owner, amount)]
//!   POST /seed/{mint}                -> body [[token_account, owner, amount], ...] from a snapshot scan
//!   GET  /ws/{mint}                  -> per-slot deltas as JSON text frames

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::json;
use tower_http::cors::CorsLayer;

use crate::engine::Shared;

pub fn router(reg: Shared) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/watch", get(list_watch))
        .route("/watch/{mint}", post(add_watch))
        .route("/watch/{mint}", delete(remove_watch))
        .route("/state/{mint}", get(state))
        .route("/holders/{mint}", get(holders))
        .route("/seed/{mint}", post(seed))
        .route("/ws/{mint}", get(ws))
        .layer(CorsLayer::permissive())
        .with_state(reg)
}

async fn health(State(reg): State<Shared>) -> Json<serde_json::Value> {
    Json(json!({ "ok": true, "watched": reg.watched().len() }))
}

async fn list_watch(State(reg): State<Shared>) -> Json<Vec<String>> {
    Json(reg.watched())
}

async fn add_watch(State(reg): State<Shared>, Path(mint): Path<String>) -> impl IntoResponse {
    if !valid_mint(&mint) {
        return (StatusCode::BAD_REQUEST, Json(json!({ "error": "invalid mint" })));
    }
    let added = reg.watch(&mint);
    (StatusCode::OK, Json(json!({ "mint": mint, "added": added })))
}

async fn remove_watch(State(reg): State<Shared>, Path(mint): Path<String>) -> Json<serde_json::Value> {
    Json(json!({ "mint": mint, "removed": reg.unwatch(&mint) }))
}

#[derive(Deserialize)]
struct TopQ {
    top: Option<usize>,
}

async fn state(State(reg): State<Shared>, Path(mint): Path<String>, Query(q): Query<TopQ>) -> impl IntoResponse {
    match reg.snapshot(&mint, q.top.unwrap_or(50)) {
        Some(s) => (StatusCode::OK, Json(serde_json::to_value(s).unwrap())),
        None => (StatusCode::NOT_FOUND, Json(json!({ "error": "not watched" }))),
    }
}

async fn holders(State(reg): State<Shared>, Path(mint): Path<String>) -> impl IntoResponse {
    match reg.holders(&mint) {
        Some(h) => (StatusCode::OK, Json(serde_json::to_value(h).unwrap())),
        None => (StatusCode::NOT_FOUND, Json(json!({ "error": "not watched" }))),
    }
}

async fn seed(State(reg): State<Shared>, Path(mint): Path<String>, Json(rows): Json<Vec<(String, String, u64)>>) -> impl IntoResponse {
    reg.watch(&mint);
    let n = rows.len();
    let ok = reg.seed(&mint, rows);
    (if ok { StatusCode::OK } else { StatusCode::NOT_FOUND }, Json(json!({ "mint": mint, "seeded": n })))
}

async fn ws(State(reg): State<Shared>, Path(mint): Path<String>, upgrade: WebSocketUpgrade) -> impl IntoResponse {
    if !valid_mint(&mint) {
        return (StatusCode::BAD_REQUEST, "invalid mint").into_response();
    }
    // Opening a socket is enough to start tracking; the first frames are the snapshot
    // and history, then live deltas.
    reg.watch(&mint);
    upgrade.on_upgrade(move |socket| handle_ws(socket, reg, mint))
}

async fn handle_ws(mut socket: WebSocket, reg: Shared, mint: String) {
    let Some(mut rx) = reg.subscribe(&mint) else { return };
    if let Some(snap) = reg.snapshot(&mint, 25) {
        let msg = json!({ "type": "snapshot", "data": snap }).to_string();
        if socket.send(Message::Text(msg.into())).await.is_err() {
            return;
        }
    }
    loop {
        tokio::select! {
            incoming = socket.recv() => {
                match incoming {
                    Some(Ok(Message::Close(_))) | None | Some(Err(_)) => return,
                    _ => {}
                }
            }
            delta = rx.recv() => {
                match delta {
                    Ok(json) => {
                        let msg = format!("{{\"type\":\"delta\",\"data\":{json}}}");
                        if socket.send(Message::Text(msg.into())).await.is_err() { return; }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                        tracing::warn!(mint, lagged = n, "ws subscriber lagged");
                    }
                    Err(_) => return,
                }
            }
        }
    }
}

fn valid_mint(m: &str) -> bool {
    (32..=48).contains(&m.len()) && m.chars().all(|c| c.is_ascii_alphanumeric())
}
