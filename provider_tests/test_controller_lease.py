from __future__ import annotations

import threading
import unittest

from default_model_providers_implement.controller_lease import ControllerLease

SESSION_A = "a" * 32
SESSION_B = "b" * 32


class FakeManager:
    def __init__(self) -> None:
        self.activations = 0
        self.revocations: list[tuple[str, str]] = []
        self.revoked = threading.Event()

    def activate(self) -> None:
        self.activations += 1

    def revoke(self, *, message: str, error_code: str) -> threading.Event:
        self.revocations.append((message, error_code))
        self.revoked.set()
        completed = threading.Event()
        completed.set()
        return completed


class ControllerLeaseTests(unittest.TestCase):
    def test_only_current_session_can_renew_or_release(self) -> None:
        manager = FakeManager()
        lease = ControllerLease(manager, timeout_seconds=1, check_interval_seconds=0.05)
        lease.start()
        try:
            self.assertTrue(lease.acquire(SESSION_A))
            self.assertFalse(lease.acquire(SESSION_B))
            self.assertFalse(lease.heartbeat(SESSION_B))
            self.assertIsNone(lease.release(SESSION_B))
            released = lease.release(SESSION_A)
            self.assertIsNotNone(released)
            self.assertEqual(manager.activations, 1)
            self.assertEqual(manager.revocations[-1][1], "controller_lease_released")
        finally:
            lease.shutdown()

    def test_missing_heartbeat_revokes_the_controller(self) -> None:
        manager = FakeManager()
        lease = ControllerLease(
            manager,
            timeout_seconds=0.08,
            check_interval_seconds=0.01,
        )
        lease.start()
        try:
            self.assertTrue(lease.acquire(SESSION_A))
            self.assertTrue(manager.revoked.wait(1))
            self.assertEqual(manager.revocations[-1][1], "controller_lease_expired")
            self.assertTrue(lease.acquire(SESSION_B))
        finally:
            lease.shutdown()

    def test_lost_lease_notifies_once_for_release_and_expiry(self) -> None:
        lost: list[str] = []
        released = ControllerLease(
            FakeManager(), timeout_seconds=1, on_lost=lambda: lost.append("released")
        )
        self.assertTrue(released.acquire(SESSION_A))
        self.assertTrue(released.heartbeat(SESSION_A))
        self.assertEqual(lost, [])
        released.release(SESSION_A)
        self.assertIsNone(released.release(SESSION_A))
        self.assertEqual(lost, ["released"])

        expired_event = threading.Event()
        expired = ControllerLease(
            FakeManager(),
            timeout_seconds=0.08,
            check_interval_seconds=0.01,
            on_lost=expired_event.set,
        )
        expired.start()
        try:
            self.assertTrue(expired.acquire(SESSION_B))
            self.assertTrue(expired_event.wait(1))
        finally:
            expired.shutdown()
