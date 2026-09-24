import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import write_profile  # noqa: E402


def test_absolute_picture_inside_root_becomes_root_relative(tmp_path):
    picture = tmp_path / ".profiles-assets" / "felix" / "felix.png"
    assert write_profile.root_relative(str(picture), str(tmp_path)) == ".profiles-assets/felix/felix.png"


def test_relative_picture_is_left_alone(tmp_path):
    assert write_profile.root_relative("profiles/a/a.png", str(tmp_path)) == "profiles/a/a.png"


def test_absolute_picture_outside_root_is_left_alone(tmp_path):
    outside = tmp_path.parent / "elsewhere.png"
    assert write_profile.root_relative(str(outside), str(tmp_path / "project")) == str(outside)


def test_missing_picture_stays_missing(tmp_path):
    assert write_profile.root_relative(None, str(tmp_path)) is None
    assert write_profile.root_relative("", str(tmp_path)) == ""
