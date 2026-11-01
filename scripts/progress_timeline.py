"""Sample the TUI progress bar during a real conversion (development helper)."""
import asyncio, sys, time
from pathlib import Path
from pdfdown.tui.app import PdfdownApp

async def main(pdf, out):
    app = PdfdownApp([Path(pdf)], Path(out))
    async with app.run_test(size=(140, 40)) as pilot:
        start, next_sample, samples = time.time(), 0, []
        while app.jobs[0].status in ("queued", "converting"):
            await pilot.pause(0.5)
            p = app.jobs[0].progress
            if p and time.time() - start >= next_sample:
                samples.append(f"{time.time() - start:4.0f}s {p.fraction() * 100:3.0f}% {p.step}")
                next_sample += 10
        total = time.time() - start
        print(f"{Path(pdf).name}: {total:.0f} s total, {app.jobs[0].status}")
        print("  " + " | ".join(samples))

asyncio.run(main(sys.argv[1], sys.argv[2]))
