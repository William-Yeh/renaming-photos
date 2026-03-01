"""Tests for rename_photos."""
import shutil
import pytest
from datetime import timedelta, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.rename_photos import (
    validate_date,
    parse_offset,
    resolve_datetime,
    build_stem,
    find_target,
    extract_exif,
    check_exiftool,
    process_file,
    collect_photos,
    MAX_COUNTER,
)


class TestValidateDate:
    def test_valid_date_returns_string(self):
        assert validate_date({'DateTimeOriginal': '2024:03:15 14:30:00'}) == '2024:03:15 14:30:00'

    def test_missing_field_returns_none(self):
        assert validate_date({}) is None

    def test_suspicious_1970_returns_none(self):
        assert validate_date({'DateTimeOriginal': '1970:01:01 00:00:00'}) is None

    def test_suspicious_zero_date_returns_none(self):
        assert validate_date({'DateTimeOriginal': '0000:00:00 00:00:00'}) is None

    def test_year_before_1990_returns_none(self):
        assert validate_date({'DateTimeOriginal': '1989:12:31 23:59:59'}) is None

    def test_year_far_future_returns_none(self):
        assert validate_date({'DateTimeOriginal': '2099:01:01 00:00:00'}) is None


class TestParseOffset:
    def test_positive_with_colon(self):
        assert parse_offset('+08:00') == timedelta(hours=8)

    def test_negative_with_colon(self):
        assert parse_offset('-05:00') == timedelta(hours=-5)

    def test_positive_without_colon(self):
        assert parse_offset('+0800') == timedelta(hours=8)

    def test_half_hour(self):
        assert parse_offset('+05:30') == timedelta(hours=5, minutes=30)

    def test_invalid_returns_none(self):
        assert parse_offset('invalid') is None

    def test_empty_returns_none(self):
        assert parse_offset('') is None

    def test_out_of_range_hours_returns_none(self):
        assert parse_offset('+25:00') is None

    def test_out_of_range_minutes_returns_none(self):
        assert parse_offset('+00:99') is None


class TestResolveDatetime:
    RAW = '2024:03:15 14:30:00'

    def test_no_tz_info_returns_no_suffix(self):
        dt, suffix = resolve_datetime(self.RAW, {}, None)
        assert suffix is None
        assert dt.year == 2024

    def test_user_tz_differs_from_local_adds_suffix(self):
        with patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=0)):
            dt, suffix = resolve_datetime(self.RAW, {}, '+08:00')
        assert suffix == ' +0800'

    def test_user_tz_same_as_local_no_suffix(self):
        with patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=8)):
            dt, suffix = resolve_datetime(self.RAW, {}, '+08:00')
        assert suffix is None

    def test_exif_offset_differs_from_local_adds_suffix(self):
        exif = {'OffsetTimeOriginal': '+09:00'}
        with patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=0)):
            dt, suffix = resolve_datetime(self.RAW, exif, None)
        assert suffix == ' +0900'

    def test_user_tz_takes_priority_over_exif(self):
        exif = {'OffsetTimeOriginal': '+09:00'}
        with patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=0)):
            dt, suffix = resolve_datetime(self.RAW, exif, '+08:00')
        assert suffix == ' +0800'

    def test_negative_offset_suffix(self):
        with patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=0)):
            dt, suffix = resolve_datetime(self.RAW, {}, '-05:00')
        assert suffix == ' -0500'


class TestBuildStem:
    def test_default_format(self):
        dt = datetime(2024, 3, 15, 14, 30, 0)
        assert build_stem(dt, None, '%Y-%m-%d %H.%M.%S') == '2024-03-15 14.30.00'

    def test_with_tz_suffix(self):
        dt = datetime(2024, 3, 15, 14, 30, 0)
        assert build_stem(dt, ' +0800', '%Y-%m-%d %H.%M.%S') == '2024-03-15 14.30.00 +0800'

    def test_custom_format(self):
        dt = datetime(2024, 3, 15, 14, 30, 0)
        assert build_stem(dt, None, '%Y%m%d_%H%M%S') == '20240315_143000'


class TestFindTarget:
    def test_no_conflict_returns_bare_name(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        target = find_target(photo, '2024-03-15 14.30.00', None, '.jpg')
        assert target == tmp_path / '2024-03-15 14.30.00.jpg'

    def test_conflict_uses_subsec(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        existing = tmp_path / '2024-03-15 14.30.00.jpg'
        existing.write_bytes(b'other')
        target = find_target(photo, '2024-03-15 14.30.00', '123', '.jpg')
        assert target == tmp_path / '2024-03-15 14.30.00 123.jpg'

    def test_conflict_no_subsec_uses_counter(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        existing = tmp_path / '2024-03-15 14.30.00.jpg'
        existing.write_bytes(b'other')
        target = find_target(photo, '2024-03-15 14.30.00', None, '.jpg')
        assert target == tmp_path / '2024-03-15 14.30.00 (1).jpg'

    def test_already_correct_name_returns_self(self, tmp_path):
        photo = tmp_path / '2024-03-15 14.30.00.jpg'
        photo.write_bytes(b'x')
        target = find_target(photo, '2024-03-15 14.30.00', None, '.jpg')
        assert target == photo

    def test_extension_lowercased(self, tmp_path):
        photo = tmp_path / 'IMG_001.JPG'
        photo.write_bytes(b'x')
        target = find_target(photo, '2024-03-15 14.30.00', None, '.JPG')
        assert target.suffix == '.jpg'

    def test_conflict_subsec_also_taken_uses_counter(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        (tmp_path / '2024-03-15 14.30.00.jpg').write_bytes(b'other1')
        (tmp_path / '2024-03-15 14.30.00 123.jpg').write_bytes(b'other2')
        target = find_target(photo, '2024-03-15 14.30.00', '123', '.jpg')
        assert target == tmp_path / '2024-03-15 14.30.00 123 (1).jpg'

    def test_counter_cap_raises(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        with patch('pathlib.Path.exists', return_value=True):
            with pytest.raises(RuntimeError, match=str(MAX_COUNTER)):
                find_target(photo, '2024-03-15 14.30.00', None, '.jpg')


class TestExtractExif:
    def test_returns_parsed_fields(self, tmp_path):
        photo = tmp_path / 'test.jpg'
        photo.write_bytes(b'x')
        fake_output = '[{"DateTimeOriginal":"2024:03:15 14:30:00","SubSecTimeOriginal":"123"}]'
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
            result = extract_exif(photo)
        assert result['DateTimeOriginal'] == '2024:03:15 14:30:00'
        assert result['SubSecTimeOriginal'] == '123'

    def test_empty_exiftool_output_returns_empty_dict(self, tmp_path):
        photo = tmp_path / 'test.jpg'
        photo.write_bytes(b'x')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[]')
            result = extract_exif(photo)
        assert result == {}

    def test_malformed_exiftool_output_returns_empty_dict(self, tmp_path):
        photo = tmp_path / 'corrupt.jpg'
        photo.write_bytes(b'x')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='')
            result = extract_exif(photo)
        assert result == {}

    def test_nonzero_exit_returns_empty_dict(self, tmp_path, capsys):
        photo = tmp_path / 'test.jpg'
        photo.write_bytes(b'x')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='Permission denied')
            result = extract_exif(photo)
        assert result == {}
        assert 'WARN' in capsys.readouterr().err


class TestCheckExiftool:
    def test_passes_when_exiftool_found(self):
        with patch('subprocess.run'):
            check_exiftool()  # should not raise or exit

    def test_exits_when_exiftool_missing(self):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            with pytest.raises(SystemExit) as exc:
                check_exiftool()
        assert exc.value.code == 1


DEFAULT_FMT = '%Y-%m-%d %H.%M.%S'


class TestProcessFile:
    def _mock_exif(self, data):
        return patch('scripts.rename_photos.extract_exif', return_value=data)

    def _mock_local(self, hours=0):
        return patch('scripts.rename_photos.local_offset', return_value=timedelta(hours=hours))

    def test_happy_path_renames_file(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local():
            result = process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert result == 'renamed'
        assert (tmp_path / '2024-03-15 14.30.00.jpg').exists()

    def test_skip_no_exif_returns_skipped(self, tmp_path, capsys):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        with self._mock_exif({}):
            result = process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert result == 'skipped'
        assert 'SKIP' in capsys.readouterr().err

    def test_skip_suspicious_date(self, tmp_path, capsys):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '1970:01:01 00:00:00'}
        with self._mock_exif(exif):
            result = process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert result == 'skipped'
        assert 'SKIP' in capsys.readouterr().err

    def test_dry_run_does_not_rename(self, tmp_path, capsys):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local():
            process_file(photo, DEFAULT_FMT, None, dry_run=True)
        assert photo.exists()
        assert '→' in capsys.readouterr().out

    def test_tz_suffix_in_filename(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local(hours=0):
            process_file(photo, DEFAULT_FMT, '+08:00', dry_run=False)
        assert (tmp_path / '2024-03-15 14.30.00 +0800.jpg').exists()

    def test_already_correct_name_returns_noop(self, tmp_path):
        photo = tmp_path / '2024-03-15 14.30.00.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local():
            result = process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert result == 'noop'
        assert photo.exists()

    def test_path_traversal_raises(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local():
            with pytest.raises(ValueError, match='escapes source directory'):
                process_file(photo, '../evil/%Y-%m-%d', None, dry_run=False)

    def test_non_digit_subsec_sanitised(self, tmp_path):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        (tmp_path / '2024-03-15 14.30.00.jpg').write_bytes(b'other')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00', 'SubSecTimeOriginal': '12 34'}
        with self._mock_exif(exif), self._mock_local():
            process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert (tmp_path / '2024-03-15 14.30.00 1234.jpg').exists()

    def test_rename_oserror_returns_error(self, tmp_path, capsys):
        photo = tmp_path / 'IMG_001.jpg'
        photo.write_bytes(b'x')
        exif = {'DateTimeOriginal': '2024:03:15 14:30:00'}
        with self._mock_exif(exif), self._mock_local():
            with patch('pathlib.Path.rename', side_effect=OSError('cross-device')):
                result = process_file(photo, DEFAULT_FMT, None, dry_run=False)
        assert result == 'error'
        assert 'ERROR' in capsys.readouterr().err


class TestCollectPhotos:
    def test_finds_jpeg(self, tmp_path):
        (tmp_path / 'a.jpg').write_bytes(b'x')
        assert tmp_path / 'a.jpg' in collect_photos([tmp_path])

    def test_finds_raw(self, tmp_path):
        (tmp_path / 'a.cr2').write_bytes(b'x')
        assert tmp_path / 'a.cr2' in collect_photos([tmp_path])

    def test_recursive(self, tmp_path):
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / 'a.jpg').write_bytes(b'x')
        assert sub / 'a.jpg' in collect_photos([tmp_path])

    def test_ignores_unsupported(self, tmp_path):
        (tmp_path / 'a.png').write_bytes(b'x')
        assert collect_photos([tmp_path]) == []

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / 'a.JPG').write_bytes(b'x')
        assert tmp_path / 'a.JPG' in collect_photos([tmp_path])


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='exiftool not installed')
class TestIntegration:
    FIXTURE = Path(__file__).parent / 'fixtures' / 'IMG_1339.jpg'

    def test_fixture_jpg_renamed_by_exif_date(self, tmp_path):
        photo = tmp_path / 'IMG_1339.jpg'
        shutil.copy(self.FIXTURE, photo)

        result = process_file(photo, '%Y-%m-%d %H.%M.%S', None, dry_run=False)

        assert result == 'renamed'
        assert not photo.exists()
        renamed = list(tmp_path.glob('*.jpg'))
        assert len(renamed) == 1
        assert renamed[0].name.startswith('2026-01-31 13.33.59')
