//! Yellowstone gRPC (Geyser) source. Subscribes to:
//!   * SPL token accounts whose mint is one of the watched mints (memcmp offset 0)
//!   * transactions that touch a watched mint (pre/post token balances -> trades)
//!   * slot updates (processed commitment) to pace flushes
//! Resubscribes on the same stream whenever the watch list changes.

use std::collections::HashMap;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use futures::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tracing::{error, info, warn};
use yellowstone_grpc_client::{ClientTlsConfig, GeyserGrpcClient};
use yellowstone_grpc_proto::geyser::subscribe_request_filter_accounts_filter::Filter;
use yellowstone_grpc_proto::geyser::subscribe_request_filter_accounts_filter_memcmp::Data;
use yellowstone_grpc_proto::geyser::subscribe_update::UpdateOneof;
use yellowstone_grpc_proto::geyser::{
    CommitmentLevel, SubscribeRequest, SubscribeRequestFilterAccounts, SubscribeRequestFilterAccountsFilter,
    SubscribeRequestFilterAccountsFilterMemcmp, SubscribeRequestFilterSlots, SubscribeRequestFilterTransactions,
    SubscribeUpdateAccount, SubscribeUpdateTransaction,
};

use crate::event::{Event, Side};

pub const TOKEN_PROGRAM: &str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
pub const TOKEN_2022_PROGRAM: &str = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";
const SPL_ACCOUNT_LEN: usize = 165;

pub struct GeyserSource {
    pub endpoint: String,
    pub x_token: Option<String>,
}

fn now_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64
}

pub fn build_request(mints: &[String]) -> SubscribeRequest {
    let mut accounts = HashMap::new();
    let mut transactions = HashMap::new();
    for mint in mints {
        let mint_bytes = bs58::decode(mint).into_vec().unwrap_or_default();
        accounts.insert(
            format!("ta-{mint}"),
            SubscribeRequestFilterAccounts {
                account: vec![],
                owner: vec![TOKEN_PROGRAM.into(), TOKEN_2022_PROGRAM.into()],
                filters: vec![SubscribeRequestFilterAccountsFilter {
                    filter: Some(Filter::Memcmp(SubscribeRequestFilterAccountsFilterMemcmp { offset: 0, data: Some(Data::Bytes(mint_bytes)) })),
                }],
                nonempty_txn_signature: None,
                cuckoo_accounts_filter: None,
            },
        );
        transactions.insert(
            format!("tx-{mint}"),
            SubscribeRequestFilterTransactions {
                vote: Some(false),
                failed: Some(false),
                signature: None,
                account_include: vec![mint.clone()],
                account_exclude: vec![],
                account_required: vec![],
                cuckoo_account_include: None,
                token_accounts: None,
            },
        );
    }
    let mut slots = HashMap::new();
    slots.insert("slots".to_string(), SubscribeRequestFilterSlots { filter_by_commitment: Some(true), interslot_updates: None });
    SubscribeRequest {
        accounts,
        slots,
        transactions,
        commitment: Some(CommitmentLevel::Processed as i32),
        ..Default::default()
    }
}

/// Decode an SPL token account (mint, owner, amount) from raw account data.
pub fn parse_token_account(data: &[u8]) -> Option<(String, String, u64)> {
    if data.len() < SPL_ACCOUNT_LEN {
        return None;
    }
    let mint = bs58::encode(&data[0..32]).into_string();
    let owner = bs58::encode(&data[32..64]).into_string();
    let amount = u64::from_le_bytes(data[64..72].try_into().ok()?);
    // state byte at 108: 0 = uninitialized, 1 = initialized, 2 = frozen
    if data[108] == 0 {
        return Some((mint, owner, 0));
    }
    Some((mint, owner, amount))
}

fn account_event(up: SubscribeUpdateAccount, watched: &[String]) -> Option<Event> {
    let info = up.account?;
    if info.lamports == 0 || info.data.len() < SPL_ACCOUNT_LEN {
        // Closed account: data is gone. The state resolves it by key.
        return Some(Event::AccountClosed { slot: up.slot, account: bs58::encode(&info.pubkey).into_string() });
    }
    let (mint, owner, amount) = parse_token_account(&info.data)?;
    if !watched.iter().any(|m| m == &mint) {
        return None;
    }
    Some(Event::TokenAccount { slot: up.slot, mint, account: bs58::encode(&info.pubkey).into_string(), owner, amount })
}

/// Derive trades from pre/post token balances: for each (owner, mint) whose balance
/// changed, emit a buy or sell of the absolute delta, with the owner's lamport delta.
pub fn transaction_events(up: SubscribeUpdateTransaction, watched: &[String]) -> Vec<Event> {
    let mut out = vec![];
    let Some(info) = up.transaction else { return out };
    let Some(meta) = info.meta else { return out };
    if meta.err.is_some() {
        return out;
    }
    let signature = bs58::encode(&info.signature).into_string();
    let keys: Vec<String> = info
        .transaction
        .and_then(|t| t.message)
        .map(|m| m.account_keys.iter().map(|k| bs58::encode(k).into_string()).collect())
        .unwrap_or_default();
    let amt = |b: &yellowstone_grpc_proto::solana::storage::confirmed_block::TokenBalance| -> u64 {
        b.ui_token_amount.as_ref().and_then(|u| u.amount.parse::<u64>().ok()).unwrap_or(0)
    };
    // (owner, mint) -> (pre, post)
    let mut deltas: HashMap<(String, String), (u64, u64)> = HashMap::new();
    for b in &meta.pre_token_balances {
        if watched.contains(&b.mint) {
            deltas.entry((b.owner.clone(), b.mint.clone())).or_default().0 += amt(b);
        }
    }
    for b in &meta.post_token_balances {
        if watched.contains(&b.mint) {
            deltas.entry((b.owner.clone(), b.mint.clone())).or_default().1 += amt(b);
        }
    }
    // Lamport delta of the fee payer / signer wallet (index 0) as the quote side.
    let payer_lamports = meta.pre_balances.first().zip(meta.post_balances.first()).map(|(a, b)| a.abs_diff(*b)).unwrap_or(0);
    for ((owner, mint), (pre, post)) in deltas {
        if pre == post {
            continue;
        }
        let side = if post > pre { Side::Buy } else { Side::Sell };
        let is_payer = keys.first().map(|k| k == &owner).unwrap_or(false);
        out.push(Event::Trade {
            slot: up.slot,
            mint,
            wallet: owner,
            side,
            amount: post.abs_diff(pre),
            lamports: if is_payer { payer_lamports } else { 0 },
            signature: signature.clone(),
        });
    }
    out
}

impl GeyserSource {
    pub async fn run(self, tx: mpsc::Sender<Event>, mut watch_rx: mpsc::UnboundedReceiver<Vec<String>>, initial: Vec<String>) {
        let mut watched = initial;
        loop {
            match self.session(&tx, &mut watch_rx, &mut watched).await {
                Ok(()) => return,
                Err(e) => {
                    error!(error = %e, "geyser session ended; reconnecting in 2s");
                    tokio::time::sleep(Duration::from_secs(2)).await;
                }
            }
        }
    }

    async fn session(
        &self,
        tx: &mpsc::Sender<Event>,
        watch_rx: &mut mpsc::UnboundedReceiver<Vec<String>>,
        watched: &mut Vec<String>,
    ) -> Result<()> {
        let mut builder = GeyserGrpcClient::build_from_shared(self.endpoint.clone())?
            .x_token(self.x_token.clone())?
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(30));
        if self.endpoint.starts_with("https://") {
            builder = builder.tls_config(ClientTlsConfig::new().with_native_roots())?;
        }
        let mut client = builder.connect().await.context("connect")?;
        let (mut sink, mut stream) = client.subscribe_with_request(Some(build_request(watched))).await.context("subscribe")?;
        info!(endpoint = %self.endpoint, mints = watched.len(), "geyser subscribed");

        loop {
            tokio::select! {
                Some(list) = watch_rx.recv() => {
                    *watched = list;
                    sink.send(build_request(watched)).await.context("resubscribe")?;
                    info!(mints = watched.len(), "geyser resubscribed");
                }
                msg = stream.next() => {
                    let Some(msg) = msg else { anyhow::bail!("stream closed") };
                    let update = msg.context("stream error")?;
                    match update.update_oneof {
                        Some(UpdateOneof::Slot(s)) => {
                            let _ = tx.send(Event::Slot { slot: s.slot, ts_ms: now_ms() }).await;
                        }
                        Some(UpdateOneof::Account(a)) => {
                            if let Some(ev) = account_event(a, watched) { let _ = tx.send(ev).await; }
                        }
                        Some(UpdateOneof::Transaction(t)) => {
                            for ev in transaction_events(t, watched) { let _ = tx.send(ev).await; }
                        }
                        Some(UpdateOneof::Ping(_)) => {
                            // Keep the stream alive.
                            let _ = sink.send(SubscribeRequest { ping: Some(yellowstone_grpc_proto::geyser::SubscribeRequestPing { id: 1 }), ..Default::default() }).await;
                        }
                        other => { if other.is_none() { warn!("empty update"); } }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_spl_token_account_layout() {
        let mut data = vec![0u8; SPL_ACCOUNT_LEN];
        data[0..32].copy_from_slice(&[7u8; 32]);
        data[32..64].copy_from_slice(&[9u8; 32]);
        data[64..72].copy_from_slice(&123_456u64.to_le_bytes());
        data[108] = 1;
        let (mint, owner, amount) = parse_token_account(&data).unwrap();
        assert_eq!(mint, bs58::encode([7u8; 32]).into_string());
        assert_eq!(owner, bs58::encode([9u8; 32]).into_string());
        assert_eq!(amount, 123_456);
        data[108] = 0;
        assert_eq!(parse_token_account(&data).unwrap().2, 0);
        assert!(parse_token_account(&data[..100]).is_none());
    }

    #[test]
    fn request_filters_each_mint() {
        let req = build_request(&["So11111111111111111111111111111111111111112".into()]);
        assert_eq!(req.accounts.len(), 1);
        assert_eq!(req.transactions.len(), 1);
        assert_eq!(req.commitment, Some(CommitmentLevel::Processed as i32));
    }
}
