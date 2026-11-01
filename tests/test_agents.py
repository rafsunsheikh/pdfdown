"""Coding agents: the --json summary, and the MCP server driven through the MCP SDK's own client."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from pdfdown.mcp_server import server

REPORT = Path(__file__).resolve().parents[1] / "corpus" / "office-report.pdf"


def test_batch_json(tmp_path):
    run = subprocess.run([sys.executable, "-m", "pdfdown.cli", "--batch", "--json", "--no-latex", str(REPORT), "-o", str(tmp_path)],
                         capture_output=True, text=True, check=True)
    data = json.loads(run.stdout)  # stdout is only the JSON; progress went to stderr
    (result,) = data["results"]
    assert Path(result["markdown"]).is_absolute() and Path(result["markdown"]).is_file()
    assert result["figures"] == 1 and result["tables"] == 1 and result["equations"]["images"] == 1
    assert "[1/1] office-report.pdf" in run.stderr and data["failed"] == []


async def call(client, tool, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result


@pytest.mark.asyncio
async def test_agent_converts_reads_and_fixes_an_equation(tmp_path):
    pdf = tmp_path / "report.pdf"
    shutil.copy(REPORT, pdf)
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"convert_pdf", "read_markdown", "list_elements", "get_element_image", "set_equation_latex"} <= names

        summary = (await call(client, "convert_pdf", path=str(pdf), read_equations=False)).structured_content
        md = summary["markdown"]
        assert md.startswith(str(tmp_path / "pdfdown-output")) and summary["equations"]["kept_as_images"][0]["id"] == "eq-1"

        outline = (await call(client, "markdown_outline", markdown_path=md)).structured_content
        assert outline["headings"][0]["title"] == "Annual Operations Review 2025"
        part = (await call(client, "read_markdown", markdown_path=md, start_line=1, max_characters=1000)).structured_content
        assert part["text"].startswith("# Annual Operations Review 2025") and part["next_start_line"]

        image = await call(client, "get_element_image", markdown_path=md, element_id="eq-1")
        assert image.content[0].type == "image"

        # pix2tex's real misreading of this equation ("α" as "Q") is refused; the right LaTeX is kept.
        wrong = (await call(client, "set_equation_latex", markdown_path=md, element_id="eq-1",
                            latex=r"S_{t}\longrightarrow Q X_{t}+(1-Q)S_{t-1}")).structured_content
        assert not wrong["accepted"] and "Q" in wrong["reason"]
        right = (await call(client, "set_equation_latex", markdown_path=md, element_id="eq-1",
                            latex=r"s_{t}=\alpha x_{t}+(1-\alpha)s_{t-1}")).structured_content
        assert right["accepted"]
        assert "$$\ns_{t}=\\alpha x_{t}+(1-\\alpha)s_{t-1}\n$$" in Path(md).read_text()
        equations = (await call(client, "list_elements", markdown_path=md, kind="equation")).structured_content
        assert equations["elements"][0]["written_as"] == "latex" and equations["elements"][0]["latex_by"] == "agent"


@pytest.mark.asyncio
async def test_missing_file_is_a_clear_error(tmp_path):
    async with Client(server) as client:
        result = await client.call_tool("convert_pdf", {"path": str(tmp_path / "nope.pdf")})
        assert result.is_error and "No such file" in result.content[0].text
