"""Make an office-style report (docx) and slide deck (pptx) for testing, then export both to PDF with LibreOffice."""
import subprocess
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.shared import Inches, Pt
from pptx import Presentation
from pptx.util import Inches as PI

out = Path(__file__).resolve().parents[1] / "corpus"; out.mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(5, 2.6), dpi=150)
ax.bar(["Q1", "Q2", "Q3", "Q4"], [120, 135, 128, 160], color="#006ba4"); ax.set_title("Quarterly revenue (k$)")
fig.tight_layout(); fig.savefig(out / "chart.png"); plt.close(fig)

d = Document()
sec = d.sections[0]
sec.header.paragraphs[0].text = "Northwind Analytics | Internal report"
footer = sec.footer.paragraphs[0]; footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
footer._p.append(parse_xml('<w:fldSimple xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'))
d.add_heading("Annual Operations Review 2025", 0)
d.add_paragraph("This report summarises operating results for the 2025 financial year. Revenue grew steadily through the year, "
                "with the strongest quarter at the end, driven by two new enterprise contracts and lower churn in the retail segment. "
                "The sections below cover revenue, regional performance, and the forecasting method used for 2026.")
d.add_heading("1. Key findings", 1)
for item in ["Revenue rose 18% year on year, to 543 thousand dollars.", "Churn fell from 6.1% to 4.3% after the support redesign.",
             "The APAC region overtook Europe as the second largest market."]:
    d.add_paragraph(item, style="List Bullet")
d.add_heading("2. Revenue by quarter", 1)
d.add_paragraph("Figure 1 shows revenue by quarter. The dip in Q3 reflects a delayed renewal that closed in October.")
d.add_picture(str(out / "chart.png"), width=Inches(4.8))
cap = d.add_paragraph("Figure 1. Quarterly revenue in thousands of dollars."); cap.runs[0].italic = True
d.add_heading("3. Regional performance", 1)
t = d.add_table(rows=5, cols=4); t.style = "Table Grid"
hdr = t.rows[0].cells; hdr[0].text = "Region"; hdr[1].merge(hdr[2]).text = "Revenue (k$)"; hdr[3].text = "Change"
rows = [("", "2024", "2025", ""), ("Americas", "250", "281", "+12%"), ("APAC", "98", "142", "+45%"), ("Europe", "112", "120", "+7%")]
for r, vals in enumerate(rows, start=1):
    for c, v in enumerate(vals):
        t.rows[r].cells[c].text = v
t.cell(0, 0).merge(t.cell(1, 0)); t.cell(0, 3).merge(t.cell(1, 3))
t.cell(0, 0).text = "Region"; t.cell(0, 3).text = "Change"
cap = d.add_paragraph("Table 1. Revenue by region, with merged header cells."); cap.runs[0].italic = True
d.add_heading("4. Forecasting method", 1)
d.add_paragraph("We forecast 2026 revenue with exponential smoothing. The smoothed level is updated each quarter as:")
omml = ('<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:oMath>'
        '<m:sSub><m:e><m:r><m:t>s</m:t></m:r></m:e><m:sub><m:r><m:t>t</m:t></m:r></m:sub></m:sSub><m:r><m:t>=α</m:t></m:r>'
        '<m:sSub><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sub><m:r><m:t>t</m:t></m:r></m:sub></m:sSub><m:r><m:t>+(1−α)</m:t></m:r>'
        '<m:sSub><m:e><m:r><m:t>s</m:t></m:r></m:e><m:sub><m:r><m:t>t−1</m:t></m:r></m:sub></m:sSub></m:oMath></m:oMathPara>')
d.add_paragraph()._p.append(parse_xml(omml))
d.add_paragraph("where α is the smoothing factor, chosen as 0.4 by cross-validation on the 2019 to 2024 quarters.")
d.add_heading("5. Next steps", 1)
for item in ["Extend the forecast to monthly granularity.", "Add confidence intervals to the dashboard.", "Review pricing for APAC renewals."]:
    d.add_paragraph(item, style="List Number")
for _ in range(3):
    d.add_paragraph("Appendix text. " * 40)
d.save(out / "office-report.docx")

p = Presentation()
s = p.slides.add_slide(p.slide_layouts[0]); s.shapes.title.text = "Q4 Business Update"; s.placeholders[1].text = "Northwind Analytics, January 2026"
s = p.slides.add_slide(p.slide_layouts[1]); s.shapes.title.text = "Highlights"
tf = s.placeholders[1].text_frame; tf.text = "Revenue up 18% year on year"
for line in ["Churn down to 4.3%", "APAC now the second largest market"]:
    tf.add_paragraph().text = line
s = p.slides.add_slide(p.slide_layouts[5]); s.shapes.title.text = "Revenue by quarter"
s.shapes.add_picture(str(out / "chart.png"), PI(1.2), PI(1.8), width=PI(7.5))
s = p.slides.add_slide(p.slide_layouts[5]); s.shapes.title.text = "Regional results"
tbl = s.shapes.add_table(4, 3, PI(1), PI(1.8), PI(8), PI(2)).table
for r, row in enumerate([("Region", "2025 (k$)", "Change"), ("Americas", "281", "+12%"), ("APAC", "142", "+45%"), ("Europe", "120", "+7%")]):
    for c, v in enumerate(row):
        tbl.cell(r, c).text = v
p.save(out / "office-slides.pptx")

for f in ("office-report.docx", "office-slides.pptx"):
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out), str(out / f)], check=True, capture_output=True)
print(sorted(x.name for x in out.iterdir()))
