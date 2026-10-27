"""Regression checks for session-bound JSON write authorization."""
import re
import unittest
from control_csrf import issue_token, valid_token


class ControlCsrfTests(unittest.TestCase):
    def setUp(self):
        self.secret = b"test-secret-not-used-in-production"
        self.session_a = b"session:1234567890.abcdef.sig"
        self.session_b = b"session:1234567890.fedcba.sig"

    def test_valid_token_for_matching_session(self):
        token = issue_token(self.secret, self.session_a)
        self.assertRegex(token, r"^[0-9a-f]{64}$")
        self.assertTrue(valid_token(self.secret, self.session_a, token))
        self.assertEqual(token, issue_token(self.secret, self.session_a))

    def test_token_is_bound_to_session(self):
        token = issue_token(self.secret, self.session_a)
        self.assertFalse(valid_token(self.secret, self.session_b, token))
        self.assertFalse(valid_token(b"other secret", self.session_a, token))

    def test_cookie_token_not_equal_to_basic_token(self):
        token = issue_token(self.secret, self.session_a)
        self.assertFalse(valid_token(self.secret, b"basic:1234567890.abcdef.sig", token))

    def test_reject_missing_invalid_or_malformed_token(self):
        correct = issue_token(self.secret, self.session_a)
        for candidate in (None, "", "wrong", correct.upper(), correct[:-1],
                          correct + "0", correct[:16] + "g" + correct[17:],
                          "0" * 65, "0" * 4096):
            with self.subTest(candidate=str(candidate)[:15]):
                self.assertFalse(valid_token(self.secret, self.session_a, candidate))
        self.assertFalse(valid_token(self.secret, self.session_a, "0"*64))

    def test_reject_unauthenticated_identity(self):
        for identity in (None, b"", "not-bytes"):
            with self.subTest(identity=identity):
                self.assertFalse(valid_token(self.secret, identity, "0"*64))
        with self.assertRaises(ValueError):
            issue_token(self.secret, b"")


if __name__ == "__main__":
    unittest.main()
