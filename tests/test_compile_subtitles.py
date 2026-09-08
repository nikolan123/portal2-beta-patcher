"""Compiler regressions, runnable with Python's standard-library unittest."""

import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "tools/compile_subtitles.py"
spec = importlib.util.spec_from_file_location("compile_subtitles", TOOL)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class CompilerTests(unittest.TestCase):
    def test_comments_escaping_and_empty_caption(self):
        source = r'''"lang" { "Language" "English" /* header */ "Tokens" {
            // "ignored" "caption"
            "test" "Hello, \"you\". <I>C:\\sound\\file"
            "empty" ""
        }}'''
        entries = compiler.parse_entries(source)
        self.assertEqual(entries, [("test", 'Hello, "you". <I>C:\\sound\\file'), ("empty", "")])

    def test_invalid_input_is_not_silently_skipped(self):
        for source in [
            '"lang" { "Tokens" { "key" "unfinished }}',
            '"lang" { "Tokens" { "key" } }',
            '"lang" { "Tokens" { "key" "caption" [$WIN32] } }',
            '"lang" { "Tokens" { "key" "caption" } } garbage',
            '"lang" { "Tokens" { "key" "caption" }',
            '"lang" { "Tokens" { "" "caption" } }',
            '/* unfinished',
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                compiler.parse_entries(source)

    def test_duplicate_names_and_crc_collisions(self):
        self.assertEqual(compiler.effective_entries([("A", "first"), ("a", "last")]), [("a", "last")])
        with patch.object(compiler.zlib, "crc32", return_value=1):
            with self.assertRaisesRegex(ValueError, "CRC collision"):
                compiler.effective_entries([("a", "first"), ("b", "second")])

    def test_blocks_unicode_and_validation(self):
        entries = [("a", "1234567"), ("b", "\U0001f600é"), ("c", "")]
        data = compiler.compile_dat(entries, 16)
        self.assertEqual(struct.unpack_from("<6I", data)[2], 2)
        self.assertEqual(list(compiler.decode_dat(data).values()), [v for _, v in entries])
        self.assertEqual(data, compiler.compile_dat(entries, 16))
        for damaged in [data[:10], data[:-1], b"BAD!" + data[4:]]:
            with self.assertRaises(ValueError):
                compiler.decode_dat(damaged)
        for size in [0, 1, 3, 65536]:
            with self.assertRaises(ValueError):
                compiler.compile_dat(entries, size)
        with self.assertRaises(ValueError):
            compiler.compile_dat([("long", "12345678")], 16)

    def test_encodings_and_cli_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "subtitles.txt"
            output = source.with_suffix(".dat")
            text = '"lang" { "Tokens" { "a" "héllo" } }'
            for encoding in ["utf-16", "utf-8", "utf-8-sig"]:
                source.write_text(text, encoding=encoding)
                self.assertEqual(compiler.read_entries(source), [("a", "héllo")])

            def run(*args):
                return subprocess.run([sys.executable, "-B", str(TOOL), str(source), *args], capture_output=True)

            self.assertEqual(run().returncode, 0)
            original = output.read_bytes()
            self.assertEqual(run("--check").returncode, 0)
            self.assertNotEqual(run(str(source)).returncode, 0)
            self.assertEqual(source.read_text(encoding="utf-8-sig"), text)
            source.write_text(text.replace("héllo", "changed"), encoding="utf-8")
            self.assertNotEqual(run("--check").returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            source.write_text('"lang" { bad', encoding="utf-8")
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_bundled_dat_matches_txt_exactly(self):
        source = compiler.DEFAULT_SOURCE
        compiled = compiler.compile_dat(compiler.read_entries(source))
        self.assertEqual(compiled, source.with_suffix(".dat").read_bytes())


if __name__ == "__main__":
    unittest.main()
