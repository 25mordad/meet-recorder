import argparse
import sys
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(prog="meetrec", description="Record meeting audio (browser + microphone) into one mono WAV.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="start recording (Ctrl+C to stop)")
    r.add_argument("--out", default="recordings", help="output folder (default: recordings)")
    r.add_argument("--app", default="chrome",
                   help="Windows: process to record, by name (chrome, msedge, firefox) or pid. Default: chrome")
    r.add_argument("--all-system", action="store_true", help="record all system audio instead of one app")
    r.add_argument("--no-mic", action="store_true", help="do not record the microphone")
    r.add_argument("--mic", default=None, help="microphone device number or name (see: meetrec devices)")
    r.add_argument("--rate", type=int, default=16000, help="output sample rate: 16000, 24000 or 48000 (default 16000)")
    r.add_argument("--chunk-seconds", type=int, default=60, help="length of each part file (default 60)")
    r.add_argument("--flush-seconds", type=float, default=2, help="how often data is forced to disk (default 2)")
    r.add_argument("--mic-gain", type=float, default=1.0)
    r.add_argument("--system-gain", type=float, default=1.0)
    r.add_argument("--keep-parts", action="store_true", help="keep the part files after joining them")

    sub.add_parser("devices", help="list microphones")

    a = sub.add_parser("assemble", help="join the part files of a recording that was interrupted")
    a.add_argument("parts_dir")
    a.add_argument("--output", default=None, help="output WAV (default: next to the parts folder)")

    args = p.parse_args(argv)

    if args.cmd == "devices":
        from .sources.mic import list_microphones
        print("\n".join(list_microphones()))
        return 0

    if args.cmd == "assemble":
        from .wavfiles import assemble
        parts = Path(args.parts_dir)
        output = Path(args.output) if args.output else parts.with_name(parts.name.removesuffix(".parts") + ".wav")
        seconds = assemble(parts, output)
        print(f"Saved {output} ({seconds:.0f} s)")
        return 0

    from .recorder import record
    try:
        record(args.out, app=args.app, all_system=args.all_system, mic=not args.no_mic, mic_device=args.mic,
               rate=args.rate, chunk_seconds=args.chunk_seconds, flush_seconds=args.flush_seconds,
               keep_parts=args.keep_parts, mic_gain=args.mic_gain, system_gain=args.system_gain)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
