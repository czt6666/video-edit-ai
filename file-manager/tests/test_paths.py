import os

import pytest

from app.paths import PathError, safe_filename, safe_join, to_rel


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.mp4").write_text("x")
    return str(tmp_path)


def test_join_root_variants(root):
    r = os.path.realpath(root)
    assert safe_join(root, "") == r
    assert safe_join(root, ".") == r
    assert safe_join(root, "/") == r


def test_join_descendant(root):
    assert safe_join(root, "raw/a.mp4") == os.path.join(os.path.realpath(root), "raw", "a.mp4")
    # leading slash is treated as root-relative, not absolute-filesystem
    assert safe_join(root, "/raw") == os.path.join(os.path.realpath(root), "raw")


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "raw/../../etc/passwd",
        "..",
        "raw/../..",
        "a/../../b",
    ],
)
def test_traversal_rejected(root, bad):
    with pytest.raises(PathError):
        safe_join(root, bad)


def test_absolute_path_is_confined(root):
    # An absolute-looking client path must NOT reach the real filesystem root.
    result = safe_join(root, "/etc/passwd")
    assert result.startswith(os.path.realpath(root))


def test_symlink_escape_rejected(root, tmp_path):
    outside = tmp_path.parent / "outside_secret"
    outside.mkdir()
    link = os.path.join(root, "sneaky")
    os.symlink(str(outside), link)
    with pytest.raises(PathError):
        safe_join(root, "sneaky")


def test_null_byte_rejected(root):
    with pytest.raises(PathError):
        safe_join(root, "raw/\x00evil")


def test_to_rel_roundtrip(root):
    p = safe_join(root, "raw/a.mp4")
    assert to_rel(root, p) == "raw/a.mp4"
    assert to_rel(root, safe_join(root, "")) == ""


@pytest.mark.parametrize("name,expected", [
    ("clip.mp4", "clip.mp4"),
    ("/a/b/clip.mp4", "clip.mp4"),
    ("..\\..\\evil.exe", "evil.exe"),
])
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


@pytest.mark.parametrize("bad", ["", "..", ".", "/", "\x00"])
def test_safe_filename_rejects(bad):
    with pytest.raises(PathError):
        safe_filename(bad)
