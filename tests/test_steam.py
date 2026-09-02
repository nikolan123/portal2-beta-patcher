from steam import parse_vdf, relevant_hl2_vpks


def test_parse_modern_libraryfolders():
    parsed = parse_vdf('''"libraryfolders" { "0" { "path" "D:\\\\Steam" "apps" { "220" "1" } } }''')
    assert parsed["libraryfolders"]["0"]["path"] == r"D:\Steam"


def test_hl2_assets_exclude_modern_voice_archive(tmp_path):
    hl2 = tmp_path / "hl2"
    hl2.mkdir()
    for name in (
        "hl2_misc_dir.vpk",
        "hl2_textures_dir.vpk",
        "hl2_sound_misc_dir.vpk",
        "hl2_sound_vo_english_dir.vpk",
    ):
        (hl2 / name).touch()

    selected = relevant_hl2_vpks(tmp_path)

    assert [path.name for path in selected] == [
        "hl2_misc_dir.vpk",
        "hl2_textures_dir.vpk",
        "hl2_sound_misc_dir.vpk",
    ]
