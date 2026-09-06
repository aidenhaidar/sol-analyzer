import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useMemo, useRef } from 'react';
import { fmtNum, fmtPrice, fmtUsd } from '../lib/format';
import { METRIC_BY_KEY, type Candle, type CandleMode, type MetricKey, type Point } from '../types';

export type Layout = 'overlay' | 'panes';

export interface MetricData {
  key: MetricKey;
  points: Point[];
  approximated?: boolean;
}

export interface HoverState {
  time: number | null;
  candle: Candle | null;
  metrics: Partial<Record<MetricKey, number>>;
}

interface Props {
  candles: Candle[];
  mode: CandleMode;
  metrics: MetricData[];
  layout: Layout;
  showVolume: boolean;
  onHover?: (h: HoverState) => void;
}

const UP = '#22c55e';
const DOWN = '#ef4444';
const GRID = '#1a1f2b';
const TEXT = '#8b93a3';
const PANE_HEIGHT = 110;

function formatFor(mode: CandleMode) {
  return mode === 'marketCap'
    ? { type: 'custom' as const, formatter: (p: number) => fmtUsd(p), minMove: 1 }
    : { type: 'custom' as const, formatter: (p: number) => fmtPrice(p), minMove: 1e-12 };
}

function metricFormat(key: MetricKey) {
  const unit = METRIC_BY_KEY[key].unit;
  return { type: 'custom' as const, formatter: (p: number) => (unit === 'usd' ? fmtUsd(p) : fmtNum(p)), minMove: 1 };
}

export function Chart({ candles, mode, metrics, layout, showVolume, onHover }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const metricRefs = useRef<Map<MetricKey, ISeriesApi<'Line' | 'Histogram'>>>(new Map());
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const candlesRef = useRef(candles);
  candlesRef.current = candles;

  const metricSignature = useMemo(() => metrics.map((m) => m.key).join(','), [metrics]);

  // Create chart once.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: TEXT,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        fontSize: 11,
        panes: { separatorColor: GRID, separatorHoverColor: '#2a3140', enableResize: true },
        attributionLogo: false,
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#3b4354', labelBackgroundColor: '#2a3140', style: LineStyle.Dashed },
        horzLine: { color: '#3b4354', labelBackgroundColor: '#2a3140', style: LineStyle.Dashed },
      },
      rightPriceScale: { borderColor: GRID, scaleMargins: { top: 0.08, bottom: 0.22 } },
      leftPriceScale: { visible: false, borderColor: GRID },
      timeScale: { borderColor: GRID, timeVisible: true, secondsVisible: false, rightOffset: 4 },
      localization: { timeFormatter: (t: Time) => new Date((t as number) * 1000).toLocaleString() },
    });
    chartRef.current = chart;

    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
      priceFormat: formatFor(mode),
    });
    volumeRef.current = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });

    const handler = (param: MouseEventParams) => {
      const cb = onHoverRef.current;
      if (!cb) return;
      if (!param.time || !candleRef.current) {
        cb({ time: null, candle: null, metrics: {} });
        return;
      }
      const t = param.time as number;
      const candle = candlesRef.current.find((c) => c.time === t) ?? null;
      const out: Partial<Record<MetricKey, number>> = {};
      for (const [key, series] of metricRefs.current) {
        const d = param.seriesData.get(series) as { value?: number } | undefined;
        if (d?.value !== undefined) out[key] = d.value;
      }
      cb({ time: t, candle, metrics: out });
    };
    chart.subscribeCrosshairMove(handler);

    return () => {
      chart.unsubscribeCrosshairMove(handler);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      metricRefs.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Candle mode changes the price formatter.
  useEffect(() => {
    candleRef.current?.applyOptions({ priceFormat: formatFor(mode) });
  }, [mode]);

  // Push candle + volume data.
  useEffect(() => {
    const cs = candleRef.current;
    const vs = volumeRef.current;
    if (!cs || !vs) return;
    cs.setData(candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    vs.setData(
      showVolume
        ? candles.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)' }))
        : [],
    );
  }, [candles, showVolume]);

  // Rebuild metric series whenever the selection or layout changes; update data otherwise.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Drop series that are no longer selected (or everything when layout flips).
    for (const [key, series] of [...metricRefs.current]) {
      if (!metrics.some((m) => m.key === key) || (series as unknown as { __layout?: Layout }).__layout !== layout) {
        chart.removeSeries(series);
        metricRefs.current.delete(key);
      }
    }
    // Remove empty extra panes left behind.
    for (let i = chart.panes().length - 1; i >= 1; i--) {
      if (chart.panes()[i].getSeries().length === 0) chart.removePane(i);
    }

    metrics.forEach((m, idx) => {
      const meta = METRIC_BY_KEY[m.key];
      let series = metricRefs.current.get(m.key);
      if (!series) {
        const paneIndex = layout === 'panes' ? chart.panes().length : 0;
        const common = {
          priceScaleId: layout === 'overlay' ? `ov-${m.key}` : 'right',
          priceFormat: metricFormat(m.key),
          lastValueVisible: layout === 'panes',
          priceLineVisible: false,
          title: layout === 'panes' ? meta.label : '',
        };
        if (meta.kind === 'histogram') {
          series = chart.addSeries(HistogramSeries, { ...common, color: meta.color + (layout === 'overlay' ? '66' : 'cc') }, paneIndex);
        } else {
          series = chart.addSeries(LineSeries, {
            ...common, color: meta.color, lineWidth: 2, crosshairMarkerVisible: true,
            lineStyle: m.approximated ? LineStyle.Dotted : LineStyle.Solid,
          }, paneIndex);
        }
        (series as unknown as { __layout?: Layout }).__layout = layout;
        metricRefs.current.set(m.key, series);

        if (layout === 'overlay') {
          // Each overlay metric floats on its own hidden scale so shapes are comparable
          // regardless of magnitude. Histograms sit low; lines fill the pane above volume.
          const margins = meta.kind === 'histogram' ? { top: 0.6, bottom: 0.22 } : { top: 0.08 + idx * 0.03, bottom: 0.22 };
          series.priceScale().applyOptions({ scaleMargins: margins, visible: false });
        } else {
          series.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 }, borderColor: GRID });
        }
      }
      series.setData(m.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    });

    // Pane heights only stick once the chart has laid the new panes out.
    if (layout === 'panes') {
      const raf = requestAnimationFrame(() => {
        chart.panes().forEach((pane, i) => { if (i > 0) pane.setHeight(PANE_HEIGHT); });
      });
      return () => cancelAnimationFrame(raf);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics, metricSignature, layout]);

  return <div ref={containerRef} className="chart" />;
}
