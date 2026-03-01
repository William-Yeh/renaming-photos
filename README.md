# renaming-photos

[![Agent Skills](https://img.shields.io/badge/agentskills.io-renaming--photos-blue)](https://agentskills.io)
[![CI](https://github.com/William-Yeh/renaming-photos/actions/workflows/test.yml/badge.svg)](https://github.com/William-Yeh/renaming-photos/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

An agent skill that renames photo files based on their EXIF shot date.

## Installation

### Recommended: `npx skills`

```bash
npx skills add William-Yeh/renaming-photos
```

### Manual installation

Copy the skill directory to your agent's skill folder:

| Agent | Directory |
|-------|-----------|
| Claude Code | `~/.claude/skills/` |
| Cursor | `.cursor/skills/` |
| Gemini CLI | `.gemini/skills/` |
| Amp | `.amp/skills/` |
| Roo Code | `.roo/skills/` |
| Copilot | `.github/skills/` |

### Prerequisites: `exiftool`

| Platform | Command |
|----------|---------|
| macOS | `brew install exiftool` |
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| Fedora/RHEL | `sudo dnf install perl-Image-ExifTool` |
| Windows | `winget install OliverBetz.ExifTool` |

Also requires [`uv`](https://docs.astral.sh/uv/getting-started/installation/).

## Usage

Tell your agent:

> Rename all photos in `~/Pictures/vacation/` by their shot date.

> `/rename-photos ~/Pictures/vacation/`

> Rename photos in `/mnt/sdcard` using Taiwan time (+08:00).

The agent will run:

```bash
uv run scripts/rename_photos.py [OPTIONS] DIR [DIR ...]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--tz +HH:MM` | auto | Force timezone offset |
| `--format STR` | `%Y-%m-%d %H.%M.%S` | strftime format string |
| `--dry-run` | off | Preview renames without executing |

### Result filename examples

| Scenario | Filename |
|----------|---------|
| Basic | `2024-03-15 14.30.00.jpg` |
| With TZ (differs from local) | `2024-03-15 14.30.00 +0800.jpg` |
| Burst (sub-second) | `2024-03-15 14.30.00 123.jpg` |

## Behavior

- Recursively traverses all specified directories
- Skips files with missing or implausible EXIF dates (warns to stderr)
- Conflict resolution: sub-second data → counter suffix
