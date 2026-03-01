"""Rename photo files based on EXIF shot date."""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUSPICIOUS_DATE_PREFIXES = {'0000:00:00', '1970:01:01'}
MIN_YEAR = 1990
MAX_YEAR_DELTA = 1  # allow up to current year + this value
SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.heic', '.cr2', '.nef', '.arw',
    '.dng', '.raf', '.rw2', '.orf', '.pef', '.srw',
}
MAX_COUNTER = 9999  # upper bound for collision counter in find_target
_MAX_YEAR = datetime.now().year + MAX_YEAR_DELTA  # computed once at startup


def validate_date(exif: dict[str, str | int]) -> str | None:
    """Return DateTimeOriginal string if valid, else None."""
    raw = exif.get('DateTimeOriginal', '')
    if not raw:
        return None
    date_part = str(raw).split(' ')[0]
    if date_part in SUSPICIOUS_DATE_PREFIXES:
        return None
    try:
        dt = datetime.strptime(str(raw), '%Y:%m:%d %H:%M:%S')
    except ValueError:
        return None
    if not (MIN_YEAR <= dt.year <= _MAX_YEAR):
        return None
    return str(raw)


def parse_offset(offset_str: str) -> timedelta | None:
    """Parse '+HH:MM' or '+HHMM' into a timedelta. Returns None if invalid."""
    m = re.match(r'^([+-])(\d{2}):?(\d{2})$', offset_str)
    if not m:
        return None
    sign = 1 if m.group(1) == '+' else -1
    hours, minutes = int(m.group(2)), int(m.group(3))
    if hours > 23 or minutes > 59:
        return None
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def local_offset() -> timedelta:
    """Return the local UTC offset as a timedelta."""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        raise RuntimeError('Could not determine local UTC offset')
    return offset


def resolve_datetime(raw_dt: str, exif: dict[str, str | int], user_tz: str | None) -> tuple[datetime, str | None]:
    """
    Parse raw_dt string and determine TZ suffix.

    Returns (datetime, tz_suffix_or_None).
    tz_suffix (e.g. ' +0800') is added when the resolved offset differs from local.
    Priority: user_tz > OffsetTimeOriginal > as-is (no offset).
    """
    dt = datetime.strptime(raw_dt, '%Y:%m:%d %H:%M:%S')

    offset = None
    if user_tz:
        offset = parse_offset(user_tz)
    elif 'OffsetTimeOriginal' in exif:
        offset = parse_offset(str(exif['OffsetTimeOriginal']))

    if offset is None:
        return dt, None

    dt = dt.replace(tzinfo=timezone(offset))

    local = local_offset()
    if offset == local:
        return dt, None

    sign = '+' if offset.total_seconds() >= 0 else '-'
    total_minutes = int(abs(offset.total_seconds()) // 60)
    h, m = divmod(total_minutes, 60)
    return dt, f' {sign}{h:02d}{m:02d}'


def build_stem(dt: datetime, tz_suffix: str | None, fmt: str) -> str:
    """Build the filename stem (no extension, no sub-second)."""
    stem = dt.strftime(fmt)
    if tz_suffix:
        stem += tz_suffix
    return stem


def find_target(path: Path, stem: str, subsec: str | None, ext: str) -> Path:
    """
    Find a non-conflicting target path for renaming.

    Priority: bare name → bare + subsec → bare + subsec + counter.
    Returns path unchanged if already correctly named.
    """
    ext = ext.lower()
    parent = path.parent

    bare = parent / f'{stem}{ext}'
    if bare == path or not bare.exists():
        return bare

    if subsec:
        with_subsec = parent / f'{stem} {subsec}{ext}'
        if with_subsec == path or not with_subsec.exists():
            return with_subsec

    base = f'{stem} {subsec}' if subsec else stem
    for counter in range(1, MAX_COUNTER + 1):
        candidate = parent / f'{base} ({counter}){ext}'
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f'Could not find a free target name for {path} after {MAX_COUNTER} attempts'
    )


def check_exiftool() -> None:
    """Verify exiftool is available on PATH. Exits with code 1 if not found."""
    try:
        subprocess.run(['exiftool', '-ver'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(
            'ERROR: exiftool not found. Install it:\n'
            '  macOS:          brew install exiftool\n'
            '  Ubuntu/Debian:  sudo apt install libimage-exiftool-perl\n'
            '  Fedora/RHEL:    sudo dnf install perl-Image-ExifTool\n'
            '  Windows:        winget install OliverBetz.ExifTool',
            file=sys.stderr,
        )
        sys.exit(1)


def extract_exif(path: Path) -> dict[str, str | int]:
    """Run exiftool on a single file and return parsed metadata dict."""
    result = subprocess.run(
        [
            'exiftool', '-json',
            '-DateTimeOriginal',
            '-SubSecTimeOriginal',
            '-OffsetTimeOriginal',
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f'WARN exiftool failed on {path.name}: {result.stderr.strip()}', file=sys.stderr)
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data[0] if data else {}


def collect_photos(directories: list[Path]) -> list[Path]:
    """Recursively find all supported photo files in given directories."""
    return sorted({
        path
        for d in directories
        for path in d.rglob('*')
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    })


def process_file(path: Path, fmt: str, user_tz: str | None, dry_run: bool) -> str:
    """
    Rename a single photo file based on EXIF date.

    Returns 'renamed' if renamed (or would rename in dry-run),
    'noop' if already correctly named, 'skipped' if no valid EXIF,
    'error' if the rename failed (e.g. cross-device OSError).
    Skipped/errored files emit a warning to stderr.
    """
    exif = extract_exif(path)
    raw_dt = validate_date(exif)
    if raw_dt is None:
        print(f'SKIP {path.name} — no valid DateTimeOriginal', file=sys.stderr)
        return 'skipped'

    dt, tz_suffix = resolve_datetime(raw_dt, exif, user_tz)
    stem = build_stem(dt, tz_suffix, fmt)
    subsec = exif.get('SubSecTimeOriginal')
    subsec_str = re.sub(r'\D', '', str(subsec)) if subsec is not None else None
    target = find_target(path, stem, subsec_str or None, path.suffix)

    if target.parent.resolve() != path.parent.resolve():
        raise ValueError(f'Target {target} escapes source directory — check --format')

    if target == path:
        return 'noop'

    if dry_run:
        print(f'{path.name} → {target.name}')
    else:
        try:
            path.rename(target)
        except OSError as e:
            print(f'ERROR renaming {path.name}: {e}', file=sys.stderr)
            return 'error'

    return 'renamed'


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Rename photo files based on EXIF DateTimeOriginal.',
    )
    parser.add_argument('dirs', nargs='+', type=Path, metavar='DIR',
                        help='directories to scan (recursively)')
    parser.add_argument('--tz', help='force timezone offset, e.g. +08:00')
    parser.add_argument(
        '--format', dest='fmt', default='%Y-%m-%d %H.%M.%S',
        help='strftime format string (default: %%(default)s)',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='print renames without executing them')
    args = parser.parse_args()

    if '/' in args.fmt or '\\' in args.fmt or '\x00' in args.fmt:
        print('ERROR: --format must not contain path separators (/ or \\) or null bytes', file=sys.stderr)
        sys.exit(1)

    check_exiftool()

    for d in args.dirs:
        if not d.is_dir():
            print(f'ERROR: {d} is not a directory', file=sys.stderr)
            sys.exit(1)

    photos = collect_photos(args.dirs)
    renamed = noop = skipped = errors = 0

    for photo in photos:
        result = process_file(photo, args.fmt, args.tz, args.dry_run)
        if result == 'renamed':
            renamed += 1
        elif result == 'noop':
            noop += 1
        elif result == 'error':
            errors += 1
        else:
            skipped += 1

    action = 'Would rename' if args.dry_run else 'Renamed'
    summary = f'{action} {renamed} file(s), {noop} already correct, skipped {skipped} file(s).'
    if errors:
        summary += f' {errors} error(s).'
    print(summary)


if __name__ == '__main__':
    main()
