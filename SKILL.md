---
name: renaming-photos
description: >
  Use when the user wants to rename photo files based on their EXIF shot date.
  Triggers when user says "rename my photos", "fix photo filenames", "sort photos
  by date", or invokes /rename-photos.
metadata:
  author: William Yeh <william.pjyeh@gmail.com>
  license: Apache-2.0
  version: 0.1.0
---

# renaming-photos

Rename photo files based on EXIF `DateTimeOriginal` by running
`scripts/rename_photos.py` (requires `uv` and `exiftool`).

## Usage

When the user invokes `/rename-photos` or asks to rename photos by date:

```bash
uv run scripts/rename_photos.py [OPTIONS] DIR [DIR ...]
```

Options:
- `--tz +HH:MM` — force timezone offset (e.g. `--tz +08:00`)
- `--format STR` — strftime format string (default: `%Y-%m-%d %H.%M.%S`)
- `--dry-run` — print what would be renamed without doing it

## Behavior

- Recursively traverses each specified directory
- Supported formats: JPEG, HEIC, CR2, NEF, ARW, DNG, RAF, RW2, ORF, PEF, SRW
- Skips files with missing or suspicious EXIF dates (warns to stderr)
- Timezone: user `--tz` > `OffsetTimeOriginal` > as-is; adds ` +HHMM` suffix
  to filename when offset differs from local
- Conflict resolution: try bare name → append sub-second → append counter
