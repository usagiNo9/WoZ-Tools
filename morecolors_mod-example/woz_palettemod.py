#!/usr/bin/env python3
"""Replace or append colors in World of Zoo's serialized EditorColorPaletteList.

Examples:
    python woz_palettemod.py replace PaletteName.txt
    python woz_palettemod.py add PaletteName.txt
    python woz_palettemod.py replace PaletteName.txt --target path/to/animaleditordata_bigcat.xml

By default, the script searches recursively below the current directory for a
unique palette data file. If exactly one candidate is inside a Preloading path,
that file is preferred. The target is backed up to TARGET.bak before writing unless --no-backup is used.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

PALETTE_KEY = b"EditorColorPaletteList"
VECTOR_TYPE = b"propertyvector"
INTLIST_MARKER = b"\x01\x07\x00\x00\x00IntList"
COLOR_BYTES = 16  # uint32 component count (3), then R, G, B as uint32 values


class PaletteError(Exception):
    """A recoverable input or serialized-data error."""


def read_palette(path: Path) -> list[tuple[int, int, int]]:
    """Read 6-digit RGB hex colors; ignore blank lines and semicolon comments."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PaletteError(f"Could not read palette file {path}: {exc}") from exc

    colors: list[tuple[int, int, int]] = []
    for line_number, original_line in enumerate(text.splitlines(), 1):
        # Semicolon begins a comment, matching the example format.
        line = original_line.split(";", 1)[0]
        # Also accept // comments.
        line = line.split("//", 1)[0]
        for token in line.split():
            token = token.strip()
            if token.startswith("#"):
                token = token[1:]
            if not re.fullmatch(r"[0-9a-fA-F]{6}", token):
                raise PaletteError(
                    f"Invalid color {token!r} on line {line_number}; "
                    "use six hexadecimal digits, e.g. FF6A00."
                )
            value = int(token, 16)
            colors.append(((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF))

    if not colors:
        raise PaletteError(f"No colors were found in {path}.")
    return colors


def encode_color(rgb: tuple[int, int, int]) -> bytes:
    return (3).to_bytes(4, "little") + b"".join(channel.to_bytes(4, "little") for channel in rgb)


def locate_palette(data: bytes) -> tuple[int, int, int]:
    """Return (count_offset, entries_offset, old_count) for the palette vector."""
    key_at = data.find(PALETTE_KEY)
    if key_at < 0:
        raise PaletteError(f"Could not find {PALETTE_KEY.decode()} in the target file.")

    # Locate the propertyvector type associated with this property name.
    vector_at = data.find(VECTOR_TYPE, key_at + len(PALETTE_KEY))
    if vector_at < 0 or vector_at - key_at > 128:
        raise PaletteError("Found the palette property name, but not its propertyvector data.")

    count_offset = vector_at + len(VECTOR_TYPE)
    if count_offset + 4 + len(INTLIST_MARKER) > len(data):
        raise PaletteError("Palette data is truncated before the IntList marker.")

    old_count = int.from_bytes(data[count_offset:count_offset + 4], "little")
    marker_at = count_offset + 4
    if data[marker_at:marker_at + len(INTLIST_MARKER)] != INTLIST_MARKER:
        raise PaletteError(
            "The palette vector does not have the expected IntList encoding; "
            "no changes were made."
        )

    entries_offset = marker_at + len(INTLIST_MARKER)
    entries_end = entries_offset + old_count * COLOR_BYTES
    if entries_end > len(data):
        raise PaletteError(
            f"Palette count says {old_count} colors, but the data ends before all entries fit."
        )

    # Sanity-check each component-count field before modifying the file.
    for i in range(old_count):
        start = entries_offset + i * COLOR_BYTES
        components = int.from_bytes(data[start:start + 4], "little")
        if components != 3:
            raise PaletteError(
                f"Unexpected palette entry {i} (component count {components}, expected 3); "
                "no changes were made."
            )
    return count_offset, entries_offset, old_count


def choose_target(explicit_target: str | None) -> Path:
    if explicit_target:
        target = Path(explicit_target).expanduser().resolve()
        if not target.is_file():
            raise PaletteError(f"Target file does not exist: {target}")
        return target

    root = Path.cwd()
    candidates: list[Path] = []
    for path in root.rglob("*.xml"):
        # Avoid scanning backup files and common virtual environments.
        if path.name.endswith(".bak") or any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if PALETTE_KEY in data:
            candidates.append(path.resolve())

    preloading = [p for p in candidates if "preloading" in str(p).lower()]
    if len(preloading) == 1:
        return preloading[0]
    if len(preloading) > 1:
        choices = "\n".join(f"  - {p}" for p in preloading)
        raise PaletteError(
            "More than one Preloading palette file was found. Specify the target with --target:\n" + choices
        )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PaletteError(
            "Could not auto-detect a palette data file below the current directory. "
            "Run this command from the extracted asset folder or pass --target PATH."
        )
    choices = "\n".join(f"  - {p}" for p in candidates)
    raise PaletteError(
        "More than one palette data file was found. Specify the intended file with --target PATH:\n" + choices
    )


def modify_target(
    target: Path, colors: list[tuple[int, int, int]], mode: str, make_backup: bool = True
) -> tuple[int, int, Path | None]:
    try:
        original = target.read_bytes()
    except OSError as exc:
        raise PaletteError(f"Could not read target file {target}: {exc}") from exc

    count_offset, entries_offset, old_count = locate_palette(original)
    if mode == "replace":
        new_colors = colors
    else:
        # Decode the original colors into RGB tuples, then append the requested colors.
        old_colors = []
        for i in range(old_count):
            start = entries_offset + i * COLOR_BYTES + 4
            channels = tuple(
                int.from_bytes(original[start + j * 4:start + (j + 1) * 4], "little")
                for j in range(3)
            )
            if any(channel > 255 for channel in channels):
                raise PaletteError(f"Existing palette entry {i} has a channel outside the RGB range.")
            old_colors.append(channels)
        new_colors = old_colors + colors

    if len(new_colors) > 0xFFFFFFFF:
        raise PaletteError("The resulting palette is too large to encode.")

    old_entries_end = entries_offset + old_count * COLOR_BYTES
    encoded_entries = b"".join(encode_color(rgb) for rgb in new_colors)
    updated = (
        original[:count_offset]
        + len(new_colors).to_bytes(4, "little")
        + original[count_offset + 4:entries_offset]
        + encoded_entries
        + original[old_entries_end:]
    )

    # Validate the newly built file before writing anything.
    _, _, verified_count = locate_palette(updated)
    if verified_count != len(new_colors):
        raise PaletteError("Internal validation failed; no changes were written.")

    backup: Path | None = None
    if make_backup:
        backup = target.with_name(target.name + ".bak")
        suffix = 1
        while backup.exists():
            backup = target.with_name(target.name + f".bak.{suffix}")
            suffix += 1

    try:
        if backup is not None:
            shutil.copy2(target, backup)
        target.write_bytes(updated)
    except OSError as exc:
        # Best-effort rollback if writing the target failed after making the backup.
        try:
            if backup is not None and backup.exists():
                shutil.copy2(backup, target)
        except OSError:
            pass
        raise PaletteError(f"Could not write modified target file: {exc}") from exc

    return old_count, len(new_colors), backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace or append colors in a World of Zoo serialized animal editor palette."
    )
    parser.add_argument("mode", choices=("replace", "add"), help="replace the full palette, or append colors")
    parser.add_argument("palette_file", help="text file containing RGB hex colors (one or more per line)")
    parser.add_argument(
        "--target", "-t",
        help="target extracted animaleditordata XML/binary file; auto-detected if omitted",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="modify the target without creating a .bak backup file",
    )
    args = parser.parse_args()

    try:
        colors = read_palette(Path(args.palette_file))
        target = choose_target(args.target)
        old_count, new_count, backup = modify_target(target, colors, args.mode, make_backup=not args.no_backup)
    except PaletteError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.mode == "replace":
        print(f"Replaced the {old_count}-color palette with {new_count} colors.")
    else:
        print(f"Added {new_count - old_count} colors to the existing {old_count}-color palette ({new_count} total).")
    print(f"Updated: {target}")
    if backup is not None:
        print(f"Backup:  {backup}")
    else:
        print("Backup:  skipped (--no-backup)")
    print("Next: put/repack this updated data file into the animal's Preloading package used by the game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
