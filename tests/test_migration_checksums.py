from interviewlens.db.migrate import checksum, transaction_body


def test_windows_and_linux_migration_text_have_the_same_checksum(tmp_path):
    linux, windows = tmp_path / "linux.sql", tmp_path / "windows.sql"
    linux.write_bytes("-- 分类\nSELECT 1;\n".encode())
    windows.write_bytes("-- 分类\r\nSELECT 1;\r\n".encode())
    assert checksum(linux) == checksum(windows)
    windows.write_bytes("-- 分类\r\nSELECT 2;\r\n".encode())
    assert checksum(linux) != checksum(windows)


def test_transaction_wrapper_removal_preserves_plpgsql_blocks():
    source = "BEGIN;\nDO $$\nBEGIN\n  PERFORM 1;\nEND\n$$;\nCOMMIT;\n"
    result = transaction_body(source)
    assert "BEGIN;" not in result and "COMMIT;" not in result
    assert "\nBEGIN\n" in result
