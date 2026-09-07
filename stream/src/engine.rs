//! Consumes normalized events, updates per-token state, and broadcasts one delta per
//! slot per token to every WebSocket subscriber.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use parking_lot::RwLock;
use tokio::sync::{broadcast, mpsc};
use tracing::{debug, info};

use crate::event::Event;
use crate::state::{Snapshot, TokenState};

pub struct Registry {
    states: RwLock<HashMap<String, TokenState>>,
    channels: RwLock<HashMap<String, broadcast::Sender<String>>>,
    /// Notified when the watch list changes so the source can resubscribe.
    watch_tx: mpsc::UnboundedSender<Vec<String>>,
}

pub type Shared = Arc<Registry>;

fn now_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64
}

impl Registry {
    pub fn new(watch_tx: mpsc::UnboundedSender<Vec<String>>) -> Shared {
        Arc::new(Self { states: RwLock::new(HashMap::new()), channels: RwLock::new(HashMap::new()), watch_tx })
    }

    pub fn watched(&self) -> Vec<String> {
        self.states.read().keys().cloned().collect()
    }

    /// Start tracking a mint. Idempotent. Returns true if it was newly added.
    pub fn watch(&self, mint: &str) -> bool {
        let added = {
            let mut states = self.states.write();
            if states.contains_key(mint) {
                false
            } else {
                states.insert(mint.to_string(), TokenState::new(mint));
                true
            }
        };
        if added {
            self.channels.write().entry(mint.to_string()).or_insert_with(|| broadcast::channel(512).0);
            info!(mint, "watching");
            let _ = self.watch_tx.send(self.watched());
        }
        added
    }

    pub fn unwatch(&self, mint: &str) -> bool {
        let removed = self.states.write().remove(mint).is_some();
        if removed {
            self.channels.write().remove(mint);
            let _ = self.watch_tx.send(self.watched());
        }
        removed
    }

    pub fn subscribe(&self, mint: &str) -> Option<broadcast::Receiver<String>> {
        self.channels.read().get(mint).map(|tx| tx.subscribe())
    }

    pub fn snapshot(&self, mint: &str, top: usize) -> Option<Snapshot> {
        self.states.read().get(mint).map(|s| s.snapshot(top))
    }

    pub fn holders(&self, mint: &str) -> Option<Vec<(String, u64)>> {
        self.states.read().get(mint).map(|s| s.holders())
    }

    pub fn seed(&self, mint: &str, rows: Vec<(String, String, u64)>) -> bool {
        let mut states = self.states.write();
        match states.get_mut(mint) {
            Some(s) => {
                s.seed(rows);
                true
            }
            None => false,
        }
    }

    /// Main loop: apply events; on each slot boundary flush every token and broadcast.
    pub async fn run(self: Shared, mut rx: mpsc::Receiver<Event>) {
        let mut current_slot: u64 = 0;
        while let Some(ev) = rx.recv().await {
            match &ev {
                Event::Slot { slot, ts_ms } => {
                    if *slot > current_slot {
                        // Flush the slot that just ended (events already applied).
                        let deltas: Vec<(String, String)> = {
                            let mut states = self.states.write();
                            states
                                .values_mut()
                                .map(|s| {
                                    let d = s.flush(current_slot.max(*slot - 1), *ts_ms);
                                    (s.mint.clone(), serde_json::to_string(&d).unwrap())
                                })
                                .collect()
                        };
                        let channels = self.channels.read();
                        for (mint, json) in deltas {
                            if let Some(tx) = channels.get(&mint) {
                                let _ = tx.send(json);
                            }
                        }
                        current_slot = *slot;
                        debug!(slot, lag_ms = now_ms().saturating_sub(*ts_ms), "slot flushed");
                    }
                }
                Event::AccountClosed { .. } => {
                    // Unknown mint: every token state checks whether it owns the key.
                    for s in self.states.write().values_mut() {
                        s.apply(&ev);
                    }
                }
                _ => {
                    if let Some(mint) = ev.mint() {
                        if let Some(s) = self.states.write().get_mut(mint) {
                            s.apply(&ev);
                        }
                    }
                }
            }
        }
    }
}
