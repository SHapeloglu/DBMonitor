import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from core.config_env import expand_env


class ExpandEnvTest(unittest.TestCase):
    def test_no_reference_returns_value_unchanged(self):
        data = {"a": "plain", "n": 5, "b": True, "x": None, "l": ["s", 1]}
        self.assertEqual(expand_env(data, env={}), data)

    def test_dollar_without_braces_is_untouched(self):
        self.assertEqual(expand_env("cost $5 {x}", env={}), "cost $5 {x}")

    def test_simple_reference_is_expanded(self):
        self.assertEqual(expand_env("${A}", env={"A": "v1"}), "v1")

    def test_reference_inside_string_is_expanded(self):
        self.assertEqual(
            expand_env("Bearer ${TOK}", env={"TOK": "abc"}), "Bearer abc"
        )

    def test_required_form_is_expanded(self):
        self.assertEqual(expand_env("${A:?need A}", env={"A": "v"}), "v")

    def test_nested_structures_are_expanded(self):
        data = {"d": [{"p": "${P}"}], "h": {"Authorization": "Bearer ${T}"}}
        out = expand_env(data, env={"P": "pw", "T": "tok"})
        self.assertEqual(out, {"d": [{"p": "pw"}], "h": {"Authorization": "Bearer tok"}})

    def test_missing_variable_raises_and_names_only_variable(self):
        with self.assertRaises(ValueError) as ctx:
            expand_env({"p": "${MISSING_X:?set it}"}, env={"OTHER": "secret-value"})
        msg = str(ctx.exception)
        self.assertIn("MISSING_X", msg)
        self.assertNotIn("secret-value", msg)

    def test_empty_variable_counts_as_missing(self):
        with self.assertRaises(ValueError):
            expand_env("${EMPTY}", env={"EMPTY": ""})

    def test_defaults_to_os_environ(self):
        with mock.patch.dict(os.environ, {"DBM_TEST_PW": "from-env"}, clear=False):
            self.assertEqual(expand_env("${DBM_TEST_PW}"), "from-env")

    def test_yaml_file_loads_after_expansion(self):
        text = (
            "databases:\n"
            "  - name: x\n"
            "    credentials:\n"
            "      user: u\n"
            "      password: ${DBM_TEST_DQ}\n"
            "notifications:\n"
            "  - headers:\n"
            "      Authorization: Bearer ${DBM_TEST_TOK}\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.yaml"
            path.write_text(text, encoding="utf-8")
            with mock.patch.dict(
                os.environ, {"DBM_TEST_DQ": "dummy-1", "DBM_TEST_TOK": "dummy-2"}
            ):
                loaded = expand_env(yaml.safe_load(path.read_text(encoding="utf-8")))
        self.assertEqual(loaded["databases"][0]["credentials"]["password"], "dummy-1")
        self.assertEqual(
            loaded["notifications"][0]["headers"]["Authorization"], "Bearer dummy-2"
        )


if __name__ == "__main__":
    unittest.main()
