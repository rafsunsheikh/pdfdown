# Recording the demo

`record.py` runs pdfdown in a pseudo-terminal of a fixed size, reads what it draws with pyte (a terminal
emulator written in Python), and draws every frame with Pillow. The recording is scripted, so it is the same
every time, whatever terminal or window size you have. Keystrokes and pauses are in the `ACTIONS` list.

## Rebuild it

```bash
uv pip install --python .venv/bin/python pyte
.venv/bin/pdfdown --batch out/examples-src/imaginary-magnetic-fields.pdf -o out/recording-run   # fill the cache first
.venv/bin/python docs/recording/record.py
```

Then encode the frames:

```bash
ffmpeg -y -framerate 10 -i docs/recording/frames/%05d.png \
  -vf "scale=1200:-2:flags=lanczos" -c:v libx264 -pix_fmt yuv420p -crf 22 -movflags +faststart docs/images/pdfdown-demo.mp4
ffmpeg -y -framerate 10 -i docs/recording/frames/%05d.png \
  -vf "scale=1000:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" \
  docs/images/pdfdown-demo.gif
```

The paper in the demo is "Imaginary magnetic fields for ultracold atoms" by S. Alminas, D. Burba and
G. Juzeliūnas (arXiv:2610.06793), licensed CC BY 4.0.
