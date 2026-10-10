import unittest
from auth import LoginGuard, SESSION_SECONDS, authenticated, sign_out


class AuthTests(unittest.TestCase):
    def test_password_gate_and_expiry(self):
        state = {}
        guard = LoginGuard()
        self.assertFalse(authenticated(state, "test-password", 1000))
        self.assertFalse(guard.attempt("a", "bad", "test-password", state, 1000)[0])
        self.assertTrue(guard.attempt("a", "test-password", "test-password", state, 1001)[0])
        self.assertTrue(authenticated(state, "test-password", 1002))
        self.assertFalse(authenticated(state, "other-password", 1002))
        self.assertFalse(authenticated(state, "test-password", 1001 + SESSION_SECONDS))

    def test_eight_failures_block_even_correct_password(self):
        guard = LoginGuard()
        for _ in range(8):
            self.assertFalse(guard.attempt("a", "bad", "test-password", {}, 1000)[0])
        self.assertFalse(guard.attempt("a", "test-password", "test-password", {}, 1001)[0])
        self.assertTrue(guard.attempt("a", "test-password", "test-password", {}, 1601)[0])

    def test_new_sessions_cannot_bypass_global_failure_budget(self):
        guard = LoginGuard()
        for i in range(100):
            guard.attempt(str(i), "bad", "test-password", {}, 1000)
        self.assertFalse(guard.attempt("new", "test-password", "test-password", {}, 1001)[0])

    def test_logout_erases_sensitive_state(self):
        state = {"login_until": 9999, "login_fingerprint": "x", "history": [], "draft_low": 5, "login_attempt_id": "a"}
        sign_out(state)
        self.assertEqual(state, {"login_attempt_id": "a"})

    def test_unicode_password(self):
        state = {}
        self.assertTrue(LoginGuard().attempt("a", "演示-password", "演示-password", state, 1000)[0])


if __name__ == "__main__":
    unittest.main()
