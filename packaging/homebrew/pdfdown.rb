# Homebrew formula for the personal tap github.com/rafsunsheikh/homebrew-tap
# Users install it with:
#   brew install rafsunsheikh/tap/pdfdown
#
# Before each release, update `url` and `sha256` to the new sdist on PyPI:
#   curl -sL https://pypi.org/pypi/pdfdown/json | jq -r '.urls[] | select(.packagetype=="sdist") | .url, .digests.sha256'
class Pdfdown < Formula
  desc "Turn PDFs, especially research articles, into clean Markdown with figures and equations"
  homepage "https://github.com/rafsunsheikh/pdfdown"
  url "https://files.pythonhosted.org/packages/source/p/pdfdown/pdfdown-0.1.2.tar.gz"
  sha256 "1f4a98828320d8a192b373effd84fa308c531cb1bcd47a876bc0b306a8b2685a"
  license "MIT"

  depends_on "python@3.14"

  def install
    python = Formula["python@3.14"].opt_bin/"python3.14"
    system python, "-m", "venv", libexec
    # PyTorch, Docling and their dependencies come as prebuilt wheels from PyPI, which
    # avoids hours of source builds. This is why the formula suits a tap, not homebrew-core.
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir", buildpath
    bin.install_symlink libexec/"bin/pdfdown"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pdfdown --version")
  end
end
