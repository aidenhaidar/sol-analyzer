//! Live per-token state: the holder set, the current slot's flow, and the deltas that
//! get pushed to browsers. Everything here is pure and synchronous so it is easy to test.

use std::collections::{HashMap, HashSet};

use serde::Serialize;

use crate::event::{Event, Side};

/// Balance below which an account no longer counts as a holder (dust).
pub const DUST: u64 = 1;

#[derive(Debug, Default)]
pub struct TokenState {
    pub mint: String,
    /// token account -> (owner, amount)
    accounts: HashMap<String, (String, u64)>,
    /// owner -> total amount across their token accounts
    holders: HashMap<String, u64>,
    /// Flow accumulated in the current (not yet flushed) slot.
    cur: SlotFlow,
    pub last_slot: u64,
    pub price_lamports_per_token: Option<f64>,
    /// Ring of recent per-slot deltas so a new subscriber can backfill its sparkline.
    pub history: Vec<SlotDelta>,
}

#[derive(Debug, Default, Clone)]
struct SlotFlow {
    buys: u32,
    sells: u32,
    buy_amount: u64,
    sell_amount: u64,
    buy_lamports: u64,
    sell_lamports: u64,
    traders: HashSet<String>,
    new_holders: u32,
    exited_holders: u32,
    changes: Vec<HolderChange>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct HolderChange {
    pub owner: String,
    pub before: u64,
    pub after: u64,
}

/// What a browser receives once per slot for a watched token.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SlotDelta {
    pub mint: String,
    pub slot: u64,
    pub ts_ms: u64,
    pub holders: usize,
    pub holder_delta: i64,
    pub new_holders: u32,
    pub exited_holders: u32,
    pub buys: u32,
    pub sells: u32,
    pub buy_amount: u64,
    pub sell_amount: u64,
    pub buy_lamports: u64,
    pub sell_lamports: u64,
    pub traders: usize,
    pub price_lamports_per_token: Option<f64>,
    /// Buy pressure minus sell pressure in tokens, normalised to -1..1.
    pub imbalance: f64,
    /// Largest balance changes this slot (owner, before, after), biggest first.
    pub top_changes: Vec<HolderChange>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Snapshot {
    pub mint: String,
    pub slot: u64,
    pub holders: usize,
    pub total_held: u64,
    pub price_lamports_per_token: Option<f64>,
    pub top_holders: Vec<(String, u64)>,
    pub history: Vec<SlotDelta>,
}

pub const HISTORY_LEN: usize = 300; // ~2 minutes of slots
const TOP_CHANGES: usize = 12;

impl TokenState {
    pub fn new(mint: &str) -> Self {
        Self { mint: mint.to_string(), ..Default::default() }
    }

    #[allow(dead_code)]
    pub fn holder_count(&self) -> usize {
        self.holders.len()
    }

    pub fn balance_of(&self, owner: &str) -> u64 {
        self.holders.get(owner).copied().unwrap_or(0)
    }

    /// Seed from a snapshot scan: (token account, owner, amount).
    pub fn seed(&mut self, rows: impl IntoIterator<Item = (String, String, u64)>) {
        for (account, owner, amount) in rows {
            self.set_account(account, owner, amount, false);
        }
        self.cur = SlotFlow::default();
    }

    pub fn apply(&mut self, ev: &Event) {
        match ev {
            Event::TokenAccount { account, owner, amount, .. } => {
                self.set_account(account.clone(), owner.clone(), *amount, true);
            }
            Event::AccountClosed { account, .. } => {
                if let Some((owner, _)) = self.accounts.get(account).cloned() {
                    self.set_account(account.clone(), owner, 0, true);
                }
            }
            Event::Trade { wallet, side, amount, lamports, .. } => {
                match side {
                    Side::Buy => {
                        self.cur.buys += 1;
                        self.cur.buy_amount += amount;
                        self.cur.buy_lamports += lamports;
                    }
                    Side::Sell => {
                        self.cur.sells += 1;
                        self.cur.sell_amount += amount;
                        self.cur.sell_lamports += lamports;
                    }
                }
                self.cur.traders.insert(wallet.clone());
            }
            Event::PoolReserves { base_amount, quote_lamports, .. } => {
                if *base_amount > 0 {
                    self.price_lamports_per_token = Some(*quote_lamports as f64 / *base_amount as f64);
                }
            }
            Event::Slot { .. } => {}
        }
    }

    fn set_account(&mut self, account: String, owner: String, amount: u64, track: bool) {
        let before_owner_total = self.balance_of(&owner);
        let prev = self.accounts.get(&account).cloned();
        if let Some((prev_owner, prev_amount)) = &prev {
            // Remove the old contribution (owner may change on account reassignment).
            let t = self.holders.entry(prev_owner.clone()).or_insert(0);
            *t = t.saturating_sub(*prev_amount);
            if *t < DUST {
                self.holders.remove(prev_owner);
            }
        }
        if amount >= DUST {
            self.accounts.insert(account, (owner.clone(), amount));
            *self.holders.entry(owner.clone()).or_insert(0) += amount;
        } else {
            self.accounts.remove(&account);
        }
        let after_owner_total = self.balance_of(&owner);
        if track && before_owner_total != after_owner_total {
            if before_owner_total < DUST && after_owner_total >= DUST {
                self.cur.new_holders += 1;
            } else if before_owner_total >= DUST && after_owner_total < DUST {
                self.cur.exited_holders += 1;
            }
            self.cur.changes.push(HolderChange { owner, before: before_owner_total, after: after_owner_total });
        }
    }

    /// Close the current slot and produce the delta to broadcast.
    pub fn flush(&mut self, slot: u64, ts_ms: u64) -> SlotDelta {
        let flow = std::mem::take(&mut self.cur);
        let holders = self.holders.len();
        let holder_delta = flow.new_holders as i64 - flow.exited_holders as i64;
        let denom = (flow.buy_amount + flow.sell_amount) as f64;
        let imbalance = if denom > 0.0 { (flow.buy_amount as f64 - flow.sell_amount as f64) / denom } else { 0.0 };
        let mut changes = flow.changes;
        changes.sort_by_key(|c| std::cmp::Reverse(c.after.abs_diff(c.before)));
        changes.truncate(TOP_CHANGES);
        let d = SlotDelta {
            mint: self.mint.clone(),
            slot,
            ts_ms,
            holders,
            holder_delta,
            new_holders: flow.new_holders,
            exited_holders: flow.exited_holders,
            buys: flow.buys,
            sells: flow.sells,
            buy_amount: flow.buy_amount,
            sell_amount: flow.sell_amount,
            buy_lamports: flow.buy_lamports,
            sell_lamports: flow.sell_lamports,
            traders: flow.traders.len(),
            price_lamports_per_token: self.price_lamports_per_token,
            imbalance,
            top_changes: changes,
        };
        self.last_slot = slot;
        self.history.push(d.clone());
        if self.history.len() > HISTORY_LEN {
            let drop = self.history.len() - HISTORY_LEN;
            self.history.drain(..drop);
        }
        d
    }

    pub fn snapshot(&self, top: usize) -> Snapshot {
        let mut holders: Vec<(String, u64)> = self.holders.iter().map(|(k, v)| (k.clone(), *v)).collect();
        holders.sort_by_key(|(_, v)| std::cmp::Reverse(*v));
        holders.truncate(top);
        Snapshot {
            mint: self.mint.clone(),
            slot: self.last_slot,
            holders: self.holders.len(),
            total_held: self.holders.values().sum(),
            price_lamports_per_token: self.price_lamports_per_token,
            top_holders: holders,
            history: self.history.clone(),
        }
    }

    /// All holders (owner, amount) for the scoring engine.
    pub fn holders(&self) -> Vec<(String, u64)> {
        self.holders.iter().map(|(k, v)| (k.clone(), *v)).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn acct(slot: u64, account: &str, owner: &str, amount: u64) -> Event {
        Event::TokenAccount { slot, mint: "M".into(), account: account.into(), owner: owner.into(), amount }
    }

    #[test]
    fn holders_follow_token_accounts() {
        let mut s = TokenState::new("M");
        s.apply(&acct(1, "a1", "alice", 100));
        s.apply(&acct(1, "b1", "bob", 50));
        assert_eq!(s.holder_count(), 2);
        // Alice opens a second token account: still one holder, bigger balance.
        s.apply(&acct(1, "a2", "alice", 25));
        assert_eq!(s.holder_count(), 2);
        assert_eq!(s.balance_of("alice"), 125);
        let d = s.flush(1, 1000);
        assert_eq!(d.new_holders, 2);
        assert_eq!(d.holder_delta, 2);

        // Bob's account is closed: holder exits even though the close carries no data.
        s.apply(&Event::AccountClosed { slot: 2, account: "b1".into() });
        let d = s.flush(2, 1400);
        assert_eq!(s.holder_count(), 1);
        assert_eq!(d.exited_holders, 1);
        assert_eq!(d.holder_delta, -1);
        assert_eq!(d.top_changes, vec![HolderChange { owner: "bob".into(), before: 50, after: 0 }]);
    }

    #[test]
    fn flow_and_imbalance() {
        let mut s = TokenState::new("M");
        let trade = |side, amount, wallet: &str| Event::Trade {
            slot: 5, mint: "M".into(), wallet: wallet.into(), side, amount, lamports: 10, signature: "sig".into(),
        };
        s.apply(&trade(Side::Buy, 300, "w1"));
        s.apply(&trade(Side::Buy, 100, "w2"));
        s.apply(&trade(Side::Sell, 100, "w1"));
        s.apply(&Event::PoolReserves { slot: 5, mint: "M".into(), base_amount: 1_000, quote_lamports: 2_000 });
        let d = s.flush(5, 2000);
        assert_eq!((d.buys, d.sells, d.traders), (2, 1, 2));
        assert!((d.imbalance - 0.6).abs() < 1e-12); // (400-100)/500
        assert_eq!(d.price_lamports_per_token, Some(2.0));
        // Next slot is quiet.
        let q = s.flush(6, 2400);
        assert_eq!((q.buys, q.imbalance), (0, 0.0));
        assert_eq!(s.history.len(), 2);
    }

    #[test]
    fn seed_does_not_count_as_flow() {
        let mut s = TokenState::new("M");
        s.seed(vec![("a".into(), "alice".into(), 10u64), ("b".into(), "bob".into(), 20)]);
        let d = s.flush(1, 0);
        assert_eq!(s.holder_count(), 2);
        assert_eq!(d.new_holders, 0);
        let snap = s.snapshot(1);
        assert_eq!(snap.top_holders, vec![("bob".to_string(), 20)]);
        assert_eq!(snap.total_held, 30);
    }
}
