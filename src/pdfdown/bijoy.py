"""Bangla text in old Bijoy fonts (SutonnyMJ, JugantorMJ ...) to Unicode Bangla.

Bijoy fonts predate Unicode Bangla: they draw Bangla letters on Latin code points, so the text layer of such a
PDF reads "gvmy` ivbv" for "মাসুদ রানা". The glyph table comes from the bijoy2unicode package (MIT,
github.com/mad-fox/bijoy2unicode). Its reordering step mishandles the reph (র্ over a consonant) and crashes on some
words, so pdfdown reorders by itself:

Bijoy stores letters in the order they are drawn. Unicode stores them in the order they are spoken. So
  1. a vowel sign drawn before its consonant (ি ে ৈ, and ে ... া for ো) moves after the consonant cluster, and
  2. a reph, drawn after the cluster it sits on (Bijoy "©"), moves before that cluster and its vowel signs.
"M‡Z©i" is গ ে ত © র as drawn; step 1 gives গ ত ে © র, step 2 gives গ র্ ত ে র (গর্তের).
"""

from __future__ import annotations

import re


REPH = ""  # placeholder for Bijoy's reph while letters are moved
PRE_KARS = set("িেৈ")
KARS = set("ািীুূৃৄেৈোৌৗ")  # vowel signs
MARKS = set("ঁংঃ")  # ঁ ং ঃ, which follow the vowel sign
HASANT, NUKTA = "্", "়"
BIJOY_FONT = re.compile(r"MJ(?:[-_ ]?(?:Bold|Italic|Regular|Light))*$|Bijoy", re.I)  # SutonnyMJ, JugantorMJBold ...


def _consonant(ch: str) -> bool:
    return "ক" <= ch <= "হ" or ch in "ড়ঢ়য়ৎ"


def _cluster_end(text: str, i: int) -> int:
    """End of the consonant cluster starting at i (consonant, nukta, then any hasant + consonant), or i if none."""
    if i >= len(text) or not _consonant(text[i]):
        return i
    j = i + 1
    while True:
        if j < len(text) and text[j] == NUKTA:
            j += 1
        if j + 1 < len(text) and text[j] == HASANT and _consonant(text[j + 1]):
            j += 2
            continue
        return j


def _cluster_start(text: list[str], i: int) -> int:
    """Start of the consonant cluster that ends just before i, after skipping its vowel signs and marks."""
    j = i
    while j > 0 and (text[j - 1] in KARS or text[j - 1] in MARKS):
        j -= 1
    if j == 0 or not _consonant(text[j - 1]) and text[j - 1] != NUKTA:
        return i  # nothing to sit on: leave the reph where it is
    j -= 1
    while j > 0 and text[j] == NUKTA:
        j -= 1
    while j >= 2 and text[j - 1] == HASANT and _consonant(text[j - 2]):
        j -= 2
    return j


def _move_pre_kars(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in PRE_KARS:
            end = _cluster_end(text, i + 1)
            if end > i + 1:
                cluster = text[i + 1:end]
                # Bijoy can type the sign inside a conjunct, where it is drawn: য ন্ ে ত্র র for যন্ত্রের.
                # The consonants with ্ just before it belong to the same cluster.
                head = []
                while len(out) >= 2 and out[-1] == HASANT and _consonant(out[-2]):
                    head[:0] = out[-2:]
                    del out[-2:]
                cluster = "".join(head) + cluster
                after = end
                if after < len(text) and text[after] == REPH:  # the reph belongs to this cluster; keep it after
                    cluster += REPH
                    after += 1
                marks = ""
                while after < len(text) and text[after] == "ঁ":  # ঁ typed between the consonant and া
                    marks += text[after]
                    after += 1
                if ch == "ে" and after < len(text) and text[after] in "াৗ":  # ে...া is ো, ে...ৗ is ৌ
                    out.append(cluster + ("ো" if text[after] == "া" else "ৌ") + marks)
                    i = after + 1
                    continue
                out.append(cluster + ch + marks)
                i = after
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _move_rephs(text: str) -> str:
    chars = list(text)
    i = 0
    while i < len(chars):
        if chars[i] == REPH:
            del chars[i]
            start = _cluster_start(chars, i)
            chars[start:start] = ["র", HASANT]
            i += 2
            continue
        i += 1
    return "".join(chars)


def to_unicode(text: str) -> str:
    """Bijoy-encoded text to Unicode Bangla. Latin text should not be passed in: it would be read as Bijoy too."""
    from bijoy2unicode import converter as table
    from bijoy2unicode.util import doCharMap

    text = doCharMap(text, table.preConversionMap)
    text = re.sub("(?<=[¯š])Í", "Z", text)  # স্ত and ন্ত: after ¯ (স্) or š (ন্), Í is the ত beneath, not ত্ম
    text = text.replace("©", REPH)
    text = doCharMap(text, table.conversionMap)
    text = doCharMap(text, table.proConversionMap)  # ্্ -> ্ before reordering: "š¿" maps to ন্ + ্ত্র
    text = _move_rephs(_move_pre_kars(text))
    text = text.replace(REPH, "র্")  # any reph that found nothing to sit on
    text = re.sub("ঁ([া-ৌৗ])", "\\1ঁ", text)  # Bijoy types ঁ before the vowel sign; Unicode after
    text = doCharMap(text, table.postConversionMap)
    # No NFC: it splits য় ড় ঢ় into two code points, which look the same but defeat search.
    return text


def is_bijoy_font(name: str) -> bool:
    return bool(name) and bool(BIJOY_FONT.search(name.split("+")[-1]))
