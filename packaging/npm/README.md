# pdfdown (npm launcher)

`npm install -g @mdrafsunsheikh/pdfdown` gives you the `pdfdown` command: a terminal app that turns PDFs, especially research articles, into clean Markdown. Tables are rebuilt, figures are cropped into image files, two-column text becomes one column, and equations become LaTeX when the LaTeX can be checked against the PDF (otherwise they stay as cropped images).

pdfdown itself is a Python package. On first run this launcher uses `uvx` if you have uv, and otherwise installs pdfdown into a private Python environment in `~/.cache/pdfdown-npm`. You need uv, or Python 3.11 to 3.14. The first install is large (about 1 GB, mostly PyTorch).

```bash
pdfdown                       # open the terminal UI
pdfdown paper.pdf             # open it with a PDF queued
pdfdown --batch paper.pdf     # convert without the UI
```

Full documentation: https://github.com/rafsunsheikh/pdfdown
