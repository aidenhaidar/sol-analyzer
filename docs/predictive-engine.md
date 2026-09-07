# Predictive engine

Pipeline: **raw chain data → engineered features → churn classifier → risk tiers → Monte Carlo cascade**.

```
api/ml/raw.py       RawWallet + collectors (RpcCollector via Solana JSON-RPC, MockCollector offline)
api/ml/features.py  feature formulas
api/ml/train.py     Random Forest vs XGBoost, 5-fold CV, saves the better one
api/ml/engine.py    scoring, z-score tiers, cascade driver
native/cascade.cpp  Monte Carlo constant-product cascade (C++), Python fallback in api/native.py
```

## Raw fields (per holder wallet)

| Field | Source (RPC) |
|---|---|
| wallet, token balance | `getTokenLargestAccounts` → `getAccountInfo` (owner, uiAmount) |
| transfer timestamps, first activity, creation slot | `getSignaturesForAddress` (blockTime, slot) |
| associated token accounts | `getTokenAccountsByOwner` |
| associated wallets (counterparties), this token's trades | sampled `getTransaction` bodies (account keys, pre/post token balances) |
| total wallet value | `getBalance` × `SOL_PRICE_USD` + token value |

Set `SOLANA_RPC_URL` to use a node; a dedicated RPC node is faster than an indexer for
this workload. Without it the `MockCollector` generates a deterministic population of
archetypes (bot, sybil, flipper, retail, diamond, whale) with labels.

## Features

| Feature | Formula |
|---|---|
| `wallet_age_days` | (now − first activity) / 86400 |
| `ecosystem_footprint` | unique mints ever held |
| `associated_wallets` | unique counterparties |
| `avg_hold_hours` | mean over sells of (sell time − preceding buy time) / 3600; open positions use age of the position |
| `tx_per_day` | outbound tx count / wallet age |
| `token_velocity` | tokens sold / tokens bought (0..1) |
| `concentration_pct` | token value / total wallet value × 100 |
| `paper_hand_ratio` | of the last 10 launches, share fully exited within 24 h |
| `sentiment_alignment` | −1..1; 0 until a social source is wired into `RawWallet.sentiment_alignment` |
| `hours_since_first_buy`, `log_balance` | position age and size |

## Classifier

`python -m api.ml.train` fits a Random Forest (bagging, parallel trees) and XGBoost
(sequential boosting) on synthetic populations, compares held-out ROC-AUC with 5-fold
stratified CV and saves the winner to `api/ml/models/churn.joblib`. Label: did the
wallet fully exit within 24 h. The API trains a model on first use if none exists.
To train on real outcomes, build `RawWallet` records from the RPC collector with
`churned_24h` filled from history and pass them through `engineer_all`.

## Output

`GET /api/risk/{mint}` scores each holder's churn probability, then tiers by z-score
against the sampled population (with absolute-probability floors so a uniformly risky
population is not all "stable"):

| Tier | Rule |
|---|---|
| critical | z ≥ 1σ or p ≥ 0.8 |
| elevated | z ≥ 0 and p ≥ 0.5 |
| watch | z ≥ −1σ and p ≥ 0.25 |
| stable | otherwise |

`risk_score` (0..100) blends the balance-weighted churn probability with the mean, so
a few risky whales matter more than many risky dust wallets.

## Cascade simulation

`GET /api/cascade/{mint}?shock=-15&absorption=0.5&sims=4000`

Model: a constant-product pool holding half the token's USD liquidity on each side.
A quote-asset (SOL) shock marks every holder down. In each round, holders whose
drawdown exceeds their panic threshold decide once, selling with probability equal
to their churn score and dumping 40–100 % of their bag (scaled by churn). Sells move
the pool price, which can trip the next tier. Between rounds dip buyers put back
`absorption` of the round's outflow. Panic threshold is derived from concentration and
paper-hand ratio (8 % drawdown for all-in wallets, up to 60 % for diversified ones).

Reported: mean/p50/p90/p99 of the pool fraction drained, mean extra price impact,
mean sellers and cascade depth, plus a histogram. In demo data a 3 % SOL dip does
nothing, 5 % trips the concentrated sybil tier, and beyond 10 % the cascade runs
through the elevated tier. It is a stress model, not a forecast: the ratios that
matter are pool depth versus the sampled holders' combined balance.
