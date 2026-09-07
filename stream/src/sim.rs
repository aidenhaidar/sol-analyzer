//! Deterministic synthetic Geyser feed: 400 ms slots, a population of holders that
//! buy and sell with a regime-switching bias so the imbalance signal moves around.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use tokio::sync::mpsc;

use crate::event::{Event, Side};

pub struct SimSource {
    pub mints: Vec<String>,
    pub slot_ms: u64,
    pub seed: u64,
}

fn now_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64
}

struct Population {
    mint: String,
    balances: Vec<u64>,
    bias: f64,
    base: u64,
    quote: u64,
}

impl Population {
    fn new(mint: &str, rng: &mut StdRng) -> Self {
        let n = 400;
        let balances = (0..n).map(|i| if i < 5 { rng.gen_range(5_000_000..40_000_000) } else { rng.gen_range(1_000..800_000) }).collect();
        Self { mint: mint.to_string(), balances, bias: 0.0, base: 200_000_000, quote: 60_000_000_000 }
    }

    /// Emits this slot's events for the population.
    fn tick(&mut self, slot: u64, rng: &mut StdRng, tx: &mpsc::Sender<Event>) {
        if rng.gen_bool(0.03) {
            self.bias = rng.gen_range(-0.6..0.6);
        }
        self.bias *= 0.98;
        let n_trades = rng.gen_range(0..6);
        for t in 0..n_trades {
            let i = rng.gen_range(0..self.balances.len());
            let buy = rng.gen_bool((0.5 + self.bias * 0.5).clamp(0.05, 0.95));
            let amount = if buy { rng.gen_range(1_000..300_000) } else { self.balances[i].min(rng.gen_range(1_000..300_000)) };
            if amount == 0 {
                continue;
            }
            // Constant-product pool moves on every trade.
            let k = self.base as u128 * self.quote as u128;
            if buy {
                self.base = self.base.saturating_sub(amount);
                self.quote = (k / self.base.max(1) as u128) as u64;
                self.balances[i] += amount;
            } else {
                self.base += amount;
                self.quote = (k / self.base as u128) as u64;
                self.balances[i] -= amount;
            }
            let wallet = format!("SimWallet{i:04}");
            let _ = tx.try_send(Event::Trade {
                slot,
                mint: self.mint.clone(),
                wallet: wallet.clone(),
                side: if buy { Side::Buy } else { Side::Sell },
                amount,
                lamports: amount as u64 * (self.quote / self.base.max(1)),
                signature: format!("sim{slot}-{t}"),
            });
            let _ = tx.try_send(Event::TokenAccount {
                slot,
                mint: self.mint.clone(),
                account: format!("SimAta{i:04}"),
                owner: wallet,
                amount: self.balances[i],
            });
        }
        let _ = tx.try_send(Event::PoolReserves { slot, mint: self.mint.clone(), base_amount: self.base, quote_lamports: self.quote });
    }
}

impl SimSource {
    pub async fn run(self, tx: mpsc::Sender<Event>) {
        let mut rng = StdRng::seed_from_u64(self.seed);
        let mut pops: Vec<Population> = self.mints.iter().map(|m| Population::new(m, &mut rng)).collect();
        // Seed initial balances as non-flow account updates in slot 0.
        let mut slot = 300_000_000u64;
        for p in &pops {
            for (i, b) in p.balances.iter().enumerate() {
                let _ = tx.send(Event::TokenAccount { slot, mint: p.mint.clone(), account: format!("SimAta{i:04}"), owner: format!("SimWallet{i:04}"), amount: *b }).await;
            }
        }
        let _ = tx.send(Event::Slot { slot, ts_ms: now_ms() }).await;
        let mut ticker = tokio::time::interval(Duration::from_millis(self.slot_ms));
        loop {
            ticker.tick().await;
            slot += 1;
            for p in pops.iter_mut() {
                p.tick(slot, &mut rng, &tx);
            }
            if tx.send(Event::Slot { slot, ts_ms: now_ms() }).await.is_err() {
                return;
            }
        }
    }
}
