"""Run the real TUI in a pseudo-terminal, wait for equations to load, press q (development helper)."""
import fcntl, os, pty, select, struct, sys, termios, time

pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-256color"
    os.execv(".venv/bin/pdfdown", [".venv/bin/pdfdown", sys.argv[1], "-o", sys.argv[2]])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 150, 0, 0))
seen = b""
def pump(seconds):
    global seen
    end = time.time() + seconds
    while time.time() < end:
        if not select.select([fd], [], [], 0.2)[0]:
            if os.waitpid(pid, os.WNOHANG) != (0, 0):
                return True
            continue
        try:
            seen += os.read(fd, 65536)
        except OSError:
            return
        if os.waitpid(pid, os.WNOHANG) != (0, 0):
            return True
stem = os.path.basename(sys.argv[1])[:-4]
md = os.path.join(sys.argv[2], stem, stem + ".md")
start = time.time()
while time.time() - start < 120:   # the Report shows "Read N equations" once pix2tex ran
    pump(1)
    if os.path.exists(md) and "$$" in open(md).read():  # LaTeX written: pix2tex has loaded and run
        break
pump(3)
termios_echo = bool(termios.tcgetattr(fd)[3] & termios.ECHO)
os.write(fd, b"q")
quit_ok = pump(10)
print(f"after loading equations: echo on = {termios_echo}; quit with q = {bool(quit_ok)} ({time.time() - start:.0f} s)")
if not quit_ok:
    os.kill(pid, 9)
