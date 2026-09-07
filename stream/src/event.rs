//! Source-agnostic events. Both the Geyser client and the simulator emit these, so the
//! state engine and the tests never depend on gRPC types.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Buy,
    Sell,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    /// A new slot started processing. `ts_ms` is the wall-clock time the source saw it.
    Slot { slot: u64, ts_ms: u64 },
    /// An SPL token account for a watched mint changed (or was created / closed).
    TokenAccount {
        slot: u64,
        mint: String,
        account: String,
        owner: String,
        /// Raw token amount (not UI amount). 0 means emptied or closed.
        amount: u64,
    },
    /// A token account was closed (lamports 0). The state resolves owner/mint by key.
    AccountClosed { slot: u64, account: String },
    /// A swap involving a watched mint, derived from a transaction's pre/post balances.
    Trade {
        slot: u64,
        mint: String,
        wallet: String,
        side: Side,
        /// Raw token amount moved.
        amount: u64,
        /// Lamports moved on the wallet's side (0 when unknown).
        lamports: u64,
        signature: String,
    },
    /// Pool vault balances for a watched mint, used to derive a live price.
    PoolReserves {
        slot: u64,
        mint: String,
        base_amount: u64,
        quote_lamports: u64,
    },
}

impl Event {
    #[allow(dead_code)]
    pub fn slot(&self) -> u64 {
        match self {
            Event::Slot { slot, .. }
            | Event::AccountClosed { slot, .. }
            | Event::TokenAccount { slot, .. }
            | Event::Trade { slot, .. }
            | Event::PoolReserves { slot, .. } => *slot,
        }
    }

    pub fn mint(&self) -> Option<&str> {
        match self {
            Event::Slot { .. } | Event::AccountClosed { .. } => None,
            Event::TokenAccount { mint, .. } | Event::Trade { mint, .. } | Event::PoolReserves { mint, .. } => Some(mint),
        }
    }
}
