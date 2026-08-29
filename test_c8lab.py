"""Hermetic tests for c8lab token() precedence. No network: every assertion
is decided before a socket would open (the fake IDP host is .invalid, so a
regression that tries HTTP fails loudly rather than silently passing)."""
import importlib
import os
import unittest


def _load(env):
    """Reload c8lab with exactly the given C8_* environment."""
    for k in [k for k in os.environ if k.startswith("C8_")]:
        del os.environ[k]
    os.environ.update(env)
    import c8lab
    return importlib.reload(c8lab)


class TokenPrecedence(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items()
                       if k.startswith("C8_")}

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("C8_")]:
            del os.environ[k]
        os.environ.update(self._saved)
        import c8lab
        importlib.reload(c8lab)

    def test_access_token_beats_keycloak(self):
        m = _load({"C8_ACCESS_TOKEN": "tok-from-env",
                   "C8_IDP": "https://auth.invalid",
                   "C8_CLIENT_SECRET": "unused"})
        self.assertEqual(m.token(), "tok-from-env")

    def test_access_token_needs_no_client_secret(self):
        m = _load({"C8_ACCESS_TOKEN": "tok-from-env",
                   "C8_IDP": "https://auth.invalid"})
        self.assertEqual(m.token(), "tok-from-env")

    def test_absent_localnet_unchanged(self):
        m = _load({})
        # LocalNet path: a self-minted HS256 JWT, three dot-separated parts.
        self.assertEqual(len(m.token().split(".")), 3)

    def test_absent_devnet_still_requires_secret(self):
        m = _load({"C8_IDP": "https://auth.invalid"})
        with self.assertRaises(m.LabError):
            m.token()


if __name__ == "__main__":
    unittest.main()
