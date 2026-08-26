"""CLI entry points: `fth` (live readout) and `fth analyze` (session report)."""

from __future__ import annotations

import argparse
import sys

from fth.ingest import TelemetryPacket, listen
from fth.session import CsvRecorder, format_report, load_csv, summarize
from fth.tuning import format_suggestions, suggest


def _live(args: argparse.Namespace) -> None:
    recorder = None
    stream = None
    if args.csv:
        stream = open(args.csv, "w", newline="")  # noqa: SIM115 - closed in finally
        recorder = CsvRecorder(stream)

    print(f"Listening on udp://{args.host}:{args.port} — start driving in FH6 (Ctrl+C to quit).")
    try:
        for pkt in listen(args.host, args.port):
            if not pkt.is_race_on:
                continue
            if recorder:
                recorder.write(pkt)
                recorder.flush()
            print(_live_line(pkt), end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        if stream:
            stream.close()
            print(f"\nSession saved to {args.csv}")


def _live_line(pkt: TelemetryPacket) -> str:
    return (
        f"\r{pkt.speed * 3.6:6.1f} km/h  "
        f"{pkt.current_engine_rpm:6.0f} rpm  "
        f"gear {pkt.gear:<2} "
        f"tires {pkt.tire_temp_front_left:4.0f}/{pkt.tire_temp_front_right:4.0f}"
        f"/{pkt.tire_temp_rear_left:4.0f}/{pkt.tire_temp_rear_right:4.0f}"
    )


def _analyze(args: argparse.Namespace) -> None:
    with open(args.log, newline="") as stream:
        packets = [p for p in load_csv(stream) if p.is_race_on]
    summary = summarize(packets)
    print(format_report(summary))
    print()
    print(format_suggestions(suggest(summary)))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fth",
        description="Forza Telemetry Helper — FH6 'Data Out' telemetry capture and analysis.",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_live = sub.add_parser("live", help="live readout while driving")
    p_live.add_argument("--host", default="127.0.0.1", help="address to bind (default: 127.0.0.1)")
    p_live.add_argument("--port", type=int, default=20777, help="UDP port (default: 20777)")
    p_live.add_argument("--csv", metavar="FILE", help="also record packets to a CSV file")

    p_an = sub.add_parser("analyze", help="print a summary report from a recorded CSV log")
    p_an.add_argument("log", help="CSV file recorded with `fth live --csv`")

    # `fth` (bare) and `fth --csv …` default to live mode
    first = sys.argv[1] if len(sys.argv) > 1 else ""
    argv = sys.argv[1:] if first in ("live", "analyze") else ["live", *sys.argv[1:]]
    args = parser.parse_args(argv)
    if args.cmd == "live":
        _live(args)
    else:
        _analyze(args)

if __name__ == "__main__":
    main()
