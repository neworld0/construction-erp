# Root Cause

The CEO project summary response was valid UTF-8 only by Django's default response encoding, but it did not declare `charset=utf-8` or prefix the stream with a UTF-8 BOM. Windows Excel can open a double-clicked BOM-less CSV using a local ANSI code page, which corrupts Korean project names.

The response now explicitly uses UTF-8, writes `U+FEFF` before the CSV header, and keeps the existing headers and row values unchanged.
