"""Translate a timestamped transcript with Claude, through the Claude Code CLI (`claude -p`).

Uses whatever login the `claude` command already has (subscription or API key), so no key is
configured here. The transcript is sent in chunks; each line keeps its [hh:mm:ss] timestamp.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SYSTEM = (
    "You are a professional translator. The user sends part of a meeting transcript produced by "
    "speech recognition. Every line starts with a timestamp like [00:01:23]. Translate the text of "
    "each line into {lang}. Rules: keep every timestamp exactly as it is; output exactly one line per "
    "input line, in the same order; do not merge, split, summarise or skip lines; keep names, product "
    "names and numbers; where recognition clearly misheard a word, translate the evident meaning; if a "
    "line is unintelligible, write [unclear]. Output only the translated lines, with no notes, no "
    "headings and no code fences."
)


def _chunks(lines, size):
    for i in range(0, len(lines), size):
        yield lines[i:i + size]


def _ask_claude(text, lang, model, context):
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("the 'claude' command (Claude Code) was not found on PATH")
    prompt = text
    if context:
        prompt = ("For context only, the original lines just before this part (do not translate or output them):\n"
                  + "\n".join(context) + "\n\n---\nTranslate these lines:\n" + text)
    # run from an empty folder so no project files or CLAUDE.md are picked up
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            [claude, "-p", "--model", model, "--tools", "", "--no-session-persistence",
             "--system-prompt", SYSTEM.format(lang=lang)],
            input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=tmp, timeout=900,
        )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed ({r.returncode}): {(r.stderr or r.stdout).strip()[:500]}")
    return [ln for ln in r.stdout.strip().splitlines() if ln.strip()]


def translate(transcript, lang, model="sonnet", chunk_lines=120, output=None):
    src = Path(transcript)
    lines = [ln.rstrip() for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError(f"{src} is empty")
    out = Path(output) if output else src.with_name(f"{src.stem}.{lang.lower().replace(' ', '-')}.txt")

    done = []
    parts = list(_chunks(lines, chunk_lines))
    for n, part in enumerate(parts, 1):
        print(f"Translating part {n}/{len(parts)} ({len(part)} lines) ...", flush=True)
        result = _ask_claude("\n".join(part), lang, model, part_context(lines, chunk_lines, n))
        if len(result) != len(part):
            print(f"  note: got {len(result)} lines for {len(part)}", file=sys.stderr)
        done.extend(result)
        out.write_text("\n".join(done) + "\n", encoding="utf-8")  # partial result survives a failure
    print(f"Saved {out}")
    return out


def part_context(lines, chunk_lines, n):
    """The last few source lines before part n, so each part starts with some context."""
    if n == 1:
        return []
    start = (n - 1) * chunk_lines
    return lines[max(0, start - 5):start]
