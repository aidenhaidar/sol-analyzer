# Live holder stream (Geyser)

The polling collector cannot meet a 1-second freshness budget. `stream/` is a Rust
service that subscribes to a Yellowstone gRPC (Geyser) feed, keeps every watched
token's holder set in memory, and pushes one delta per slot (~400 ms) to browsers.

```
Geyser gRPC ──► sol-stream (Rust)        ──► WebSocket /ws/{mint}  ──► browser LiveStrip
                 per-mint TokenState          one JSON delta per slot      + holders overlay
                 ▲ HTTP /holders /state /seed
                 └─ api (Python) rescoring churn from live balances every 2 s
```

## What is subscribed

For each watched mint (`stream/src/geyser.rs`):

* **Accounts**: SPL Token and Token-2022 accounts with `memcmp(offset 0) == mint`, at
  *processed* commitment. The 165-byte layout is decoded directly (mint, owner, amount,
  state). A closed account arrives with no data and is resolved by key.
* **Transactions**: non-vote, non-failed transactions that mention the mint. Trades are
  derived from pre/post token balances per owner; the fee payer's lamport delta is the
  quote side. Every balance change is a buy or a sell of that size.
* **Slots**: pace the flush. On each new slot every token state emits a `SlotDelta`:
  holder count and delta, new/exited holders, buys/sells, amounts, lamports, unique
  traders, pool price if reserves were seen, `imbalance` = (buy − sell)/(buy + sell),
  and the largest balance changes.

Changing the watch list sends a new `SubscribeRequest` on the open stream, so adding a
token in the UI takes effect within a slot.

## Latency

Measured in-process: **1 ms** from the stream seeing a slot to the browser frame (simulated
feed). With a provider stream add their block-to-you latency, typically 100–300 ms for
LaserStream/Triton in the same region, well inside a 1 s budget. The strip shows the
live figure and turns amber if nothing arrives for 3 s.

## Running

```bash
make stream                         # build
./stream/target/release/sol-stream --sim               # synthetic feed on :8790
GEYSER_ENDPOINT=https://laserstream-mainnet-ewr.helius-rpc.com GEYSER_X_TOKEN=... \
  ./stream/target/release/sol-stream --watch <mint>    # real feed
```

`make dev` starts the simulated stream, the API with `STREAM_ORIGIN`, and Vite (which
proxies `/ws`). In production Caddy routes `/ws/*` to the stream container and requires
the same shared secret the Worker adds; the Worker passes WebSocket upgrades through.

## HTTP API of the stream

```
GET    /health
GET    /watch                 POST /watch/{mint}     DELETE /watch/{mint}
GET    /state/{mint}?top=50   snapshot + last 300 slot deltas
GET    /holders/{mint}        [[owner, raw_amount], ...]
POST   /seed/{mint}           [[token_account, owner, raw_amount], ...]
GET    /ws/{mint}             {"type":"snapshot"} then {"type":"delta"} frames
```

## How the model uses it

`api/ml/live.py` builds the holder set from the stream's balances and attaches slow
wallet features (age, footprint, paper-hand ratio) from the RPC or mock collector,
cached per wallet for 6 hours. `GET /api/risk/{mint}` therefore reflects balances as of
the last slot, and is cached for 2 s instead of 60 s when the stream is enabled.

## Providers

Any Yellowstone-compatible endpoint works: Helius LaserStream, Triton One, or the
`yellowstone-grpc-geyser` plugin on your own node. The `geyser` cargo feature can be
disabled to build a simulator-only binary without protoc.
