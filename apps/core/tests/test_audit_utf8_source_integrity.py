from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCAN_GLOBS = [
    "apps/**/tests/test_audit*.py",
]

# Keep this list numeric/ASCII-only so the scanner itself cannot introduce mojibake.
BAD_CODEPOINTS = {
    0xFFFD,  # Unicode replacement character
    0x7644,
    0x71C1,
    0x7E79,
    0x6C83,
    0x7344,
    0x4EA6,
    0x6930,
    0x8881,
    0x91AB,
    0xF9D0,
    0x5360,
    0x7B4C,
}

SUSPICIOUS_RANGES = [
    (0x00A0, 0x00FF, "latin1-supplement"),
    (0x0600, 0x06FF, "arabic"),
    (0x4E00, 0x9FFF, "cjk-han"),
]

REQUIRED_STRINGS = {
    "apps/labor/tests/test_audit5_excel_reliability.py": [
        "\ubcf4\ud1b5\uc778\ubd80",
        "\ud14c\uc2a4\ud2b8\uc740\ud589",
        "\uc804\uc790\uce74\ub4dc",
        "AUDIT5 \uc2e4\uc81c \ud604\uc7a5",
        "AUDIT5 \uc2e0\uace0 \ud604\uc7a5",
        "\ud64d\uae38\ub3d9",
        "\uad6d\ub3c446\ud638\uc120 \ud3ec\uc7a5 \ubcf4\uc218\uacf5\uc0ac",
        "\ub300\ud55c\uac74\uc124",
    ],
    "apps/projects/tests/test_audit7_field_progress_e2e.py": [
        "AUDIT7 \uc2e4\uc81c \ud604\uc7a5",
        "AUDIT7 \ub2e4\ub978 \ud604\uc7a5",
        "AUDIT7 \ube44\uacf5\uac1c \ud604\uc7a5",
        "AUDIT7 \ud55c\uae00 \ud604\uc7a5",
        "\ud3ec\uc7a5 CBS",
        "\uc608\uc0b0",
        "\uc9c4\ud589\ub960 E2E \uc608\uc0b0",
        "\ud3ec\uc7a5\uacf5\uc0ac",
        "\ud604\uc7a5 \uc9c4\ud589\ub960 \uba54\ubaa8",
        "\uc624\ub298 \uc9c4\ud589\ub960 \uc785\ub825",
        "\uc120\ud0dd \uac00\ub2a5\ud55c \uc791\uc5c5\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
        "WBS \uae30\uc900\uc120 \uc791\uc5c5\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
        "\uc791\uc5c5\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4",
        "\ud0c0 \ud604\uc7a5 \uc791\uc5c5",
        "\uc811\uadfc \uac00\ub2a5 \uc791\uc5c5",
        "\ube44\uacf5\uac1c \uc791\uc5c5",
        "\ub9c8\uac10\ub418\uc5c8\uc2b5\ub2c8\ub2e4",
        "\ud504\ub85c\uc81d\ud2b8\uac00 \ub9c8\uac10\ub418\uc5c8\uc2b5\ub2c8\ub2e4",
        "\ud759\ud130\ud30c\uae30",
        "\ud759\ud130\ud30c\uae30 \uc9c4\ud589",
        "\ub418\uba54\uc6b0\uae30",
        "\ub418\uba54\uc6b0\uae30 CBS",
    ],
    "apps/projects/tests/test_audit8_ceo_dashboard_lineage.py": [
        "AUDIT8 \uc2e4\uc81c \ud604\uc7a5",
        "AUDIT8 A\ud604\uc7a5",
        "AUDIT8 B\ud604\uc7a5",
        "AUDIT8 \ud55c\uac15 \ud604\uc7a5",
        "AUDIT8 \ube44\ud65c\uc131 \ud604\uc7a5",
        "AUDIT8 \ub9c8\uac10 \ud604\uc7a5",
        "AUDIT8 \uac1c\uc778\uc815\ubcf4 \ud604\uc7a5",
        "AUDIT8 \ub9c1\ud06c \ud604\uc7a5",
        "\ud1a0\uacf5\uc0ac",
        "\ud3ec\uc7a5\uacf5\uc0ac",
        "\uc608\uc0b0",
        "\uc2e4\ud589\uc6d0\uac00",
        "\uc9c4\ud589\ub960",
        "\uc190\uc775",
        "\ud504\ub85c\uc81d\ud2b8 \uc694\uc57d",
        "\ud0dc\uc2a4\ud06c \uc9c4\ud589 \ud604\ud669",
    ],
}


def _iter_audit_files():
    seen = set()
    for pattern in SCAN_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def _has_question_mark_adjacent_to_hangul(text):
    for index, char in enumerate(text):
        if char != "?":
            continue
        left = text[index - 1] if index > 0 else ""
        right = text[index + 1] if index + 1 < len(text) else ""
        if ("\uac00" <= left <= "\ud7a3") or ("\uac00" <= right <= "\ud7a3"):
            return True
    return False


def _suspicious_range_hits(text):
    hits = []
    for start, end, label in SUSPICIOUS_RANGES:
        chars = sorted({char for char in text if start <= ord(char) <= end})
        if chars:
            rendered = " ".join(f"U+{ord(char):04X}" for char in chars[:20])
            hits.append(f"{label}: {rendered}")
    return hits


@pytest.mark.parametrize("path", list(_iter_audit_files()))
def test_audit_source_files_do_not_contain_korean_mojibake(path):
    text = path.read_text(encoding="utf-8-sig")
    rel_path = path.relative_to(ROOT).as_posix()

    bad_hits = [f"U+{code:04X}" for code in sorted(BAD_CODEPOINTS) if chr(code) in text]
    suspicious_hits = _suspicious_range_hits(text)
    missing_required = [value for value in REQUIRED_STRINGS.get(rel_path, []) if value not in text]

    assert not bad_hits, f"{rel_path} contains mojibake codepoints: {bad_hits}"
    assert not suspicious_hits, f"{rel_path} contains suspicious unicode ranges: {suspicious_hits}"
    assert ("?" * 2) not in text, f"{rel_path} contains double question marks, possible mojibake"
    assert not _has_question_mark_adjacent_to_hangul(text), (
        f"{rel_path} contains '?' adjacent to Hangul, possible mojibake"
    )
    assert not missing_required, f"{rel_path} is missing required Korean fixtures: {missing_required}"
