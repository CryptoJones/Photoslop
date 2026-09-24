# SPDX-License-Identifier: Apache-2.0
"""Every rejection path in ``photoslop.resources`` (#406).

These are the checks that stand between untrusted input and an allocation, so
each one is driven to its refusal here rather than left to be exercised by
whichever format happens to reach it.
"""

import io
import zipfile

import pytest

from photoslop import resources
from photoslop.resources import (
    ResourceBudget,
    ResourceLimitError,
    parse_xml_limited,
    read_archive_member,
    read_limited,
    validate_archive_members,
    validate_dimensions,
    validate_dpi,
)

SMALL = ResourceBudget(
    max_dimension=100,
    max_pixels=5_000,
    max_working_bytes=1 << 20,
    max_archive_bytes=100,
    max_entry_bytes=60,
    max_archive_entries=3,
    max_compression_ratio=5.0,
    max_xml_bytes=200,
    max_xml_nodes=5,
    max_xml_depth=3,
)


def test_physical_memory_falls_back_when_sysconf_is_unavailable(monkeypatch):
    def unavailable(_name):
        raise OSError("no sysconf")

    monkeypatch.setattr(resources.os, "sysconf", unavailable)
    assert resources._physical_memory() == 4 << 30


@pytest.mark.parametrize(
    ("width", "height", "message"),
    [
        (True, 10, "invalid dimensions"),
        (10, False, "invalid dimensions"),
        (0, 10, "must be positive"),
        (10, -1, "must be positive"),
        (100, 51, "maximum canvas area"),
    ],
)
def test_validate_dimensions_rejects(width, height, message):
    with pytest.raises(ResourceLimitError, match=message):
        validate_dimensions(width, height, operation="probe", budget=SMALL)


def test_validate_dimensions_accepts_the_boundary():
    validate_dimensions(100, 50, budget=SMALL)


@pytest.mark.parametrize("dpi", [0, 0.5, 2401, float("nan"), float("inf")])
def test_validate_dpi_rejects_out_of_range(dpi):
    with pytest.raises(ResourceLimitError, match="DPI must be in 1..2400"):
        validate_dpi(dpi)


@pytest.mark.parametrize("dpi", [1, 72, 2400])
def test_validate_dpi_accepts_range(dpi):
    validate_dpi(dpi)


def test_read_limited_rejects_a_file_over_the_maximum(tmp_path):
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 11)
    with pytest.raises(ResourceLimitError, match="file is 11 bytes; maximum is 10"):
        read_limited(str(path), 10, operation="probe")
    assert read_limited(str(path), 11, operation="probe") == b"x" * 11


def test_read_limited_rejects_a_file_that_grows_after_the_size_check(tmp_path, monkeypatch):
    path = tmp_path / "growing.bin"
    path.write_bytes(b"x" * 20)
    monkeypatch.setattr(resources.os.path, "getsize", lambda _p: 5)
    with pytest.raises(ResourceLimitError, match="input exceeds 10 bytes"):
        read_limited(str(path), 10, operation="probe")


def test_parse_xml_rejects_oversize_source():
    with pytest.raises(ResourceLimitError, match="XML exceeds 200 bytes"):
        parse_xml_limited(b"<a>" + b" " * 200 + b"</a>", operation="probe", budget=SMALL)


def test_parse_xml_rejects_malformed_source():
    with pytest.raises(ValueError, match="invalid or unsafe XML"):
        parse_xml_limited(b"<a><b></a>", operation="probe", budget=SMALL)


def test_parse_xml_rejects_too_many_nodes():
    with pytest.raises(ResourceLimitError, match="XML exceeds 5 nodes"):
        parse_xml_limited(b"<a>" + b"<b/>" * 5 + b"</a>", operation="probe", budget=SMALL)


def test_parse_xml_rejects_deep_nesting():
    with pytest.raises(ResourceLimitError, match="XML nesting exceeds 3"):
        parse_xml_limited(b"<a><b><c><d/></c></b></a>", operation="probe", budget=SMALL)


def test_parse_xml_accepts_within_limits():
    root = parse_xml_limited(b"<a><b><c/></b></a>", operation="probe", budget=SMALL)
    assert root.tag == "a"


def _archive(members: dict[str, bytes], *, compression=zipfile.ZIP_STORED) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def test_archive_rejects_too_many_entries():
    zf = _archive({f"m{i}": b"" for i in range(4)})
    with pytest.raises(ResourceLimitError, match="too many entries \\(4\\)"):
        validate_archive_members(zf.infolist(), budget=SMALL)


@pytest.mark.parametrize("name", ["/abs", "../up", "a/../../up", "a\\..\\up"])
def test_archive_rejects_unsafe_member_paths(name):
    info = zipfile.ZipInfo(name)
    with pytest.raises(ResourceLimitError, match="unsafe member path"):
        validate_archive_members([info], budget=SMALL)


def test_archive_rejects_duplicate_members():
    infos = [zipfile.ZipInfo("same"), zipfile.ZipInfo("same")]
    with pytest.raises(ResourceLimitError, match="duplicate member 'same'"):
        validate_archive_members(infos, budget=SMALL)


def test_archive_rejects_encrypted_members():
    info = zipfile.ZipInfo("secret")
    info.flag_bits |= 0x1
    with pytest.raises(ResourceLimitError, match="encrypted entries are unsupported"):
        validate_archive_members([info], budget=SMALL)


def test_archive_rejects_an_oversize_member():
    zf = _archive({"big": b"x" * 61})
    with pytest.raises(ResourceLimitError, match="member 'big' is too large"):
        validate_archive_members(zf.infolist(), budget=SMALL)


def test_archive_rejects_a_suspicious_compression_ratio():
    zf = _archive({"bomb": b"\0" * 60}, compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(ResourceLimitError, match="suspicious compression ratio for 'bomb'"):
        validate_archive_members(zf.infolist(), budget=SMALL)


def test_archive_rejects_an_oversize_expanded_total():
    zf = _archive({"a": b"x" * 50, "b": b"y" * 51})
    with pytest.raises(ResourceLimitError, match="expanded archive is too large"):
        validate_archive_members(zf.infolist(), budget=SMALL)


def test_archive_accepts_and_indexes_safe_members():
    zf = _archive({"a": b"x" * 10, "dir\\b": b"y"})
    by_name = validate_archive_members(zf.infolist(), budget=SMALL)
    assert sorted(by_name) == ["a", "dir/b"]
    assert read_archive_member(zf, by_name["a"], operation="probe", budget=SMALL) == b"x" * 10


def test_read_archive_member_rejects_a_size_that_disagrees_with_the_header():
    zf = _archive({"a": b"x" * 10})
    info = zf.getinfo("a")
    info.file_size = 20  # the header now over-states what the member holds
    with pytest.raises(ResourceLimitError, match="member size changed while reading"):
        read_archive_member(zf, info, operation="probe", budget=SMALL)
