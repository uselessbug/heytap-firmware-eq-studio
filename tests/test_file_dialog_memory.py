import json

import pytest

from heytap_eq.preferences import FILE_DIALOG_KINDS, FileDialogMemory


def test_each_directory_survives_restart_without_overwriting_other_categories(tmp_path):
    memory = FileDialogMemory(tmp_path/"preferences.json")
    expected = {}
    for kind in sorted(FILE_DIALOG_KINDS):
        directory = tmp_path/kind/"中文 目录"
        directory.mkdir(parents=True)
        memory.remember(kind, directory/"selected.txt")
        expected[kind] = str(directory)
    restored = FileDialogMemory(memory.path)
    assert {kind: restored.directory(kind) for kind in FILE_DIALOG_KINDS} == expected
    before = memory.path.read_bytes()
    restored.remember("eq_import", "")
    assert memory.path.read_bytes() == before


def test_removed_directories_fall_back_without_replacing_removable_drive_preferences(tmp_path):
    selected, fallback = tmp_path/"selected", tmp_path/"fallback"
    selected.mkdir()
    fallback.mkdir()
    memory = FileDialogMemory(tmp_path/"preferences.json")
    memory.remember("firmware_export", selected/"modified.bin")
    selected.rmdir()
    assert memory.directory("firmware_export", str(fallback)) == str(fallback)
    assert memory.directory("eq_import", str(tmp_path/"missing")) == ""
    assert memory.directories["firmware_export"] == str(selected)


@pytest.mark.parametrize("data", ["broken", "[]", '{"directories": null}',
                                  '{"directories": {"eq_import": 4, "target_import": "relative"}}'])
def test_malformed_path_preferences_do_not_prevent_startup(tmp_path, data):
    path = tmp_path/"preferences.json"
    path.write_text(data, encoding="utf-8")
    assert FileDialogMemory(path).directories == {}


def test_unknown_keys_are_ignored_and_cannot_be_written(tmp_path):
    path = tmp_path/"preferences.json"
    path.write_text(json.dumps({"directories": {"unknown": str(tmp_path), "eq_import": str(tmp_path)}}))
    memory = FileDialogMemory(path)
    assert memory.directories == {"eq_import": str(tmp_path)}
    with pytest.raises(ValueError):
        memory.remember("unknown", tmp_path/"file.txt")
