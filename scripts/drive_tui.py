"""Drive the TUI headlessly and save SVG screenshots (development helper)."""
import asyncio, sys, time
from pathlib import Path
from pdfdown.tui.app import PdfdownApp, ElementItem

pdf = Path(sys.argv[1]); out = Path(sys.argv[2]); shots = out / "shots"; shots.mkdir(parents=True, exist_ok=True)

async def main():
    app = PdfdownApp([pdf], out)
    async with app.run_test(size=(150, 48)) as pilot:
        start = time.time()
        while app.jobs[0].status in ("queued", "converting") and time.time() - start < 600:
            await pilot.pause(0.5)
        print("status:", app.jobs[0].status, app.jobs[0].message)
        await pilot.pause(1)
        app.save_screenshot(str(shots / "1-markdown.svg"))
        items = list(app.query(ElementItem))
        print("elements:", [i.query_one("Label").content for i in items])
        eqs = [i for i in items if i.block.kind == "equation"]
        app.query_one("#elements").focus()
        app.query_one("#elements").index = items.index(eqs[-1])
        await pilot.press("enter"); await pilot.pause(1.5)
        app.save_screenshot(str(shots / "2-element.svg"))
        await pilot.press("t"); await pilot.pause(2)
        print("after t:", eqs[-1].block.extra.get("use"), "|", Path(app.jobs[0].markdown.parent / "pdfdown-edits.json").read_text())
        await pilot.press("e"); await pilot.pause(1.5)
        app.save_screenshot(str(shots / "3-edit.svg"))
        await pilot.press("escape"); await pilot.pause(0.5)
        await pilot.press("c"); await pilot.pause(1.5)
        await pilot.press("down", "down"); await pilot.pause(1)
        app.save_screenshot(str(shots / "4-crop.svg"))
        await pilot.press("escape"); await pilot.pause(0.5)
        app.query_one("#tabs").active = "tab-report"; await pilot.pause(0.5)
        app.save_screenshot(str(shots / "5-report.svg"))
        app.query_one("#tabs").active = "tab-page"; await pilot.pause(1)
        app.save_screenshot(str(shots / "6-page.svg"))

asyncio.run(main())
