"""Start `pdfdown mcp` as a real subprocess over stdio, convert a PDF with equations, and report (development helper)."""
import sys, time, anyio
from mcp.client.client import Client
from mcp import StdioServerParameters

pdf, out = sys.argv[1], sys.argv[2]

async def main():
    params = StdioServerParameters(command=".venv/bin/pdfdown", args=["mcp"])
    progress = []
    async def on_progress(value, total, message):
        progress.append(message)
    start = time.time()
    async with Client(params) as client:
        tools = [t.name for t in (await client.list_tools()).tools]
        print("tools:", tools)
        result = await client.call_tool("convert_pdf", {"path": pdf, "output_dir": out}, read_timeout_seconds=900,
                                        progress_callback=on_progress)
        s = result.structured_content
        print("error:", result.is_error, "| equations:", s["equations"]["total"], "latex:", s["equations"]["latex"],
              "| took", round(time.time() - start), "s")
        print("progress messages:", len(progress), progress[:3], "...", progress[-1:])
        part = await client.call_tool("read_markdown", {"markdown_path": s["markdown"], "max_characters": 400})
        print("first lines:", part.structured_content["text"][:160].replace("\n", " | "))

anyio.run(main)
