"""Does importing readline undo raw mode? (development helper)"""
import os, pty, sys, termios, time, tty

result = "out/readline-probe.txt"
pid, fd = pty.fork()
if pid == 0:
    try:
        tty.setraw(0)
        before = termios.tcgetattr(0)[3]
        if sys.argv[1:] == ["block"]:
            sys.modules["readline"] = None
        try:
            import readline  # noqa: F401
        except ImportError:
            pass
        after = termios.tcgetattr(0)[3]
        msg = f"{sys.argv[1:]}: ECHO {bool(before & termios.ECHO)} -> {bool(after & termios.ECHO)}, ICANON {bool(before & termios.ICANON)} -> {bool(after & termios.ICANON)}\n"
    except Exception as e:
        msg = f"error {e!r}\n"
    with open(result, "a") as f:
        f.write(msg)
    os._exit(0)
while os.waitpid(pid, os.WNOHANG) == (0, 0):
    try:
        os.read(fd, 4096)
    except OSError:
        break
    time.sleep(0.05)
