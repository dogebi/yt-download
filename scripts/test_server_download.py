#!/usr/bin/env python3
"""Server download response behavior checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server.app as app_module


def test_guess_media_type_for_mp4():
    assert app_module.guess_media_type("example.mp4") == "video/mp4"


def test_guess_media_type_for_mp3():
    assert app_module.guess_media_type("example.mp3") == "audio/mpeg"


def test_guess_media_type_defaults_to_octet_stream():
    assert app_module.guess_media_type("example.bin") == "application/octet-stream"


def test_is_complete_download_rejects_partial_files(tmp_path):
    partial = tmp_path / "song.mp3.part"
    partial.write_bytes(b"abc")

    assert app_module.is_complete_download(partial) is False


def test_is_complete_download_accepts_final_files(tmp_path):
    final = tmp_path / "song.mp3"
    final.write_bytes(b"abc")

    assert app_module.is_complete_download(final) is True
