mod engine;
mod event;
#[cfg(feature = "geyser")]
mod geyser;
mod server;
mod sim;
mod state;

use clap::Parser;
use tokio::sync::mpsc;
use tracing_subscriber::EnvFilter;

/// Real-time holder/trade state for Solana tokens, from Geyser, over WebSocket.
#[derive(Parser, Debug)]
#[command(version)]
struct Args {
    /// Yellowstone gRPC endpoint, e.g. https://laserstream-mainnet-ewr.helius-rpc.com
    #[arg(long, env = "GEYSER_ENDPOINT")]
    geyser_endpoint: Option<String>,
    /// x-token for the endpoint
    #[arg(long, env = "GEYSER_X_TOKEN")]
    x_token: Option<String>,
    /// Use the synthetic feed instead of Geyser
    #[arg(long, env = "STREAM_SIM")]
    sim: bool,
    /// Mints to track at startup (comma separated)
    #[arg(long, env = "STREAM_WATCH", value_delimiter = ',')]
    watch: Vec<String>,
    #[arg(long, env = "STREAM_PORT", default_value_t = 8790)]
    port: u16,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt().with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into())).init();
    let args = Args::parse();

    let (event_tx, event_rx) = mpsc::channel(65_536);
    let (watch_tx, watch_rx) = mpsc::unbounded_channel();
    let reg = engine::Registry::new(watch_tx);
    for m in &args.watch {
        reg.watch(m);
    }

    if args.sim || args.geyser_endpoint.is_none() {
        let mints = if args.watch.is_empty() {
            vec!["DemoBONK1111111111111111111111111111111111111".to_string()]
        } else {
            args.watch.clone()
        };
        for m in &mints {
            reg.watch(m);
        }
        tracing::info!(?mints, "running with SIMULATED feed (no GEYSER_ENDPOINT)");
        tokio::spawn(sim::SimSource { mints, slot_ms: 400, seed: 7 }.run(event_tx));
        drop(watch_rx);
    } else {
        #[cfg(feature = "geyser")]
        {
            let src = geyser::GeyserSource { endpoint: args.geyser_endpoint.clone().unwrap(), x_token: args.x_token.clone() };
            let initial = reg.watched();
            tokio::spawn(src.run(event_tx, watch_rx, initial));
        }
        #[cfg(not(feature = "geyser"))]
        anyhow::bail!("built without the `geyser` feature; use --sim");
    }

    tokio::spawn(reg.clone().run(event_rx));

    let app = server::router(reg);
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", args.port)).await?;
    tracing::info!(port = args.port, "sol-stream listening");
    axum::serve(listener, app).await?;
    Ok(())
}
