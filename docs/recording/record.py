"""Record a scripted pdfdown session to PNG frames, for the README's GIF and MP4.

There is no screen grab here. The app runs in a pseudo-terminal of a fixed
size, pyte (a terminal emulator in Python) reads what it draws, and Pillow
draws each frame with a real monospace font. So the recording is the same
every time, whoever runs it and whatever their window size.

Image previews in the app use half blocks ("▀" with a top and a bottom colour);
they are drawn here as two solid rectangles, so previews look as they do in a
real terminal.

Usage (from the repository root):
    .venv/bin/python docs/recording/record.py            # frames in docs/recording/frames
    .venv/bin/python docs/recording/record.py --peek      # also print the screen text at each "peek" step

Then encode, see docs/recording/README.md.
"""
from __future__ import annotations

import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/recording/frames"
COLS, ROWS = 120, 34
FPS = 10
CELL_W, CELL_H = 11, 22
FONT_SIZE = 18
PAD = 16
FONT_PATH = "/System/Library/Fonts/Menlo.ttc"
FG, BG = "e6edf3", "0d1117"
NAMED = {"black": "2e3436", "red": "ff6b6b", "green": "06d6a0", "brown": "ffd166", "yellow": "ffd166",
         "blue": "5f9ed1", "magenta": "c678dd", "cyan": "56b6c2", "white": "e6edf3", "default": None}

PAPER = ROOT / "out/examples-src/imaginary-magnetic-fields.pdf"
WORK = ROOT / "out/recording-run"
CMD = [str(ROOT / ".venv/bin/pdfdown"), str(PAPER), "-o", str(WORK)]

DOWN, UP, TAB = "\x1b[B", "\x1b[A", "\t"

# (action, argument, seconds to show the result). "hidden" runs without drawing frames,
# so the GIF starts with the paper already converted rather than with a loading screen.
ACTIONS = [
    ("until", "✓ imaginary", 600),  # wait, without drawing, until the paper is converted
    ("wait", 3.0),                  # the converted Markdown
    ("keys", "2", 3.0),             # the Markdown source, with checked LaTeX between $$
    ("keys", "1", 0.6),
    ("keys", TAB, 0.6),             # focus the element list
    ("keys", DOWN, 0.8),
    ("keys", "\r", 2.6),            # open Figure 1 in the Element tab
    ("keys", "4", 2.6),             # its page, crop in red
    ("peek",),
    ("keys", "3", 0.8),
    ("keys", DOWN, 1.4),
    ("keys", DOWN, 2.4),            # an equation: LaTeX or image, and why
    ("peek",),
    ("keys", "e", 3.0),             # the LaTeX editor with its live check
    ("keys", "\x1b", 1.0),
    ("keys", "5", 3.0),             # the report
    ("keys", "1", 1.5),
]


def colour(value: str, fallback: str) -> tuple[int, int, int]:
    value = NAMED.get(value, value) or fallback
    if len(value) != 6:
        value = fallback
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return tuple(int(fallback[i:i + 2], 16) for i in (0, 2, 4))


def render(screen: pyte.Screen, font, bold, path: Path) -> None:
    img = Image.new("RGB", (COLS * CELL_W + PAD * 2, ROWS * CELL_H + PAD * 2), colour(BG, BG))
    d = ImageDraw.Draw(img)
    for y in range(ROWS):
        line = screen.buffer[y]
        for x in range(COLS):
            ch = line[x]
            fg, bg = ch.fg, ch.bg
            if ch.reverse:
                fg, bg = bg, fg
            x0, y0 = PAD + x * CELL_W, PAD + y * CELL_H
            if ch.data == "▀":  # half block: top half in the foreground colour, bottom half in the background
                d.rectangle([x0, y0, x0 + CELL_W, y0 + CELL_H // 2], fill=colour(fg, FG))
                d.rectangle([x0, y0 + CELL_H // 2, x0 + CELL_W, y0 + CELL_H], fill=colour(bg, BG))
                continue
            if bg != "default":
                d.rectangle([x0, y0, x0 + CELL_W, y0 + CELL_H], fill=colour(bg, BG))
            if ch.data and ch.data != " ":
                d.text((x0, y0), ch.data, font=bold if ch.bold else font, fill=colour(fg, FG))
    img.save(path)


def main() -> None:
    peek = "--peek" in sys.argv
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE, index=0)
    bold = ImageFont.truetype(FONT_PATH, FONT_SIZE, index=1)
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)

    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
        os.execv(CMD[0], CMD)
        os._exit(1)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    frame = 0

    def pump(seconds: float, draw: bool = True) -> None:
        nonlocal frame
        end = time.monotonic() + seconds
        nxt = time.monotonic()
        while time.monotonic() < end:
            if select.select([fd], [], [], 0.02)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                stream.feed(data)
            now = time.monotonic()
            if draw and now >= nxt:
                render(screen, font, bold, OUT / f"{frame:05d}.png")
                frame += 1
                nxt += 1 / FPS

    for action in ACTIONS:
        kind = action[0]
        if kind == "hidden":
            pump(action[1], draw=False)
        elif kind == "until":
            deadline = time.monotonic() + action[2]
            while action[1] not in "\n".join(screen.display) and time.monotonic() < deadline:
                pump(0.5, draw=False)
        elif kind == "wait":
            pump(action[1])
        elif kind == "keys":
            os.write(fd, action[1].encode())
            pump(action[2])
        elif kind == "peek" and peek:
            print("\n".join(screen.display), "\n" + "=" * COLS)

    os.kill(pid, signal.SIGTERM)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    print(f"{frame} frames at {FPS} fps, {frame / FPS:.1f} seconds")


if __name__ == "__main__":
    main()
