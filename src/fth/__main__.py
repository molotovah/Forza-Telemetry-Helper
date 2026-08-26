"""CLI entry point: `fth` prints a live telemetry readout from FH6."""

from __future__ import annotations

import argparse

from fth.ingest import listen


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fth",
        description="Forza Telemetry Helper — live readout of FH6 'Data Out' telemetry.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=20777, help="UDP port to bind (default: 20777)")
    args = parser.parse_args()

    print(f"Listening on udp://{args.host}:{args.port} — start driving in FH6 (Ctrl+C to quit).")
    try:
        for pkt in listen(args.host, args.port):
            if not pkt.is_race_on:
                continue
            print(
                f"\r{pkt.speed * 3.6:6.1f} km/h  "
                f"{pkt.current_engine_rpm:6.0f} rpm  "
                f"gear {pkt.gear:<2} "
                f"tires {pkt.tire_temp_front_left:4.0f}/{pkt.tire_temp_front_right:4.0f}"
                f"/{pkt.tire_temp_rear_left:4.0f}/{pkt.tire_temp_rear_right:4.0f}",
                end="",
                flush=True,
            )
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
