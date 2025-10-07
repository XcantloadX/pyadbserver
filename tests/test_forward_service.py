import asyncio
import sys
import os
from typing import List, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pyadbserver.services import ForwardService
from tests.base_test import AdbServerTestCase
from pyadbserver.transport.device_manager import SingleDeviceService


class TestForwardService(AdbServerTestCase):
    def get_services(self, device_manager: SingleDeviceService) -> List[Any]:
        """Register the ForwardService."""
        return [ForwardService()]
    
    async def test_list_empty_forwards(self):
        """Test listing forwards when none are set."""
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertEqual(rc, 0, f"adb forward --list failed: {err}")
        self.assertEqual(out.strip(), "")

    async def test_add_and_list_forward(self):
        """Test adding a forward and then listing it."""
        rc, out, err = await self._run_adb("forward", "tcp:6000", "tcp:7000")
        self.assertEqual(rc, 0, f"adb forward failed: {err}")

        rc, out, err = await self._run_adb("forward", "--list")
        self.assertEqual(rc, 0, f"adb forward --list failed: {err}")
        self.assertIn("test-5554 tcp:6000 tcp:7000", out)

    async def test_add_and_remove_forward(self):
        """Test adding a forward and then removing it."""
        # Add forward
        rc, out, err = await self._run_adb("forward", "tcp:6001", "tcp:7001")
        self.assertEqual(rc, 0, f"adb forward failed: {err}")

        # Verify it's listed
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertIn("test-5554 tcp:6001 tcp:7001", out)

        # Remove forward
        rc, out, err = await self._run_adb("forward", "--remove", "tcp:6001")
        self.assertEqual(rc, 0, f"adb forward --remove failed: {err}")

        # Verify it's gone
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertEqual(out.strip(), "")

    async def test_remove_all_forwards(self):
        """Test adding multiple forwards and removing them all."""
        await self._run_adb("forward", "tcp:6002", "tcp:7002")
        await self._run_adb("forward", "tcp:6003", "tcp:7003")

        # Verify they are listed
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertIn("tcp:6002", out)
        self.assertIn("tcp:6003", out)

        # Remove all
        rc, out, err = await self._run_adb("forward", "--remove-all")
        self.assertEqual(rc, 0, f"adb forward --remove-all failed: {err}")

        # Verify list is empty
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertEqual(out.strip(), "")

    async def test_forward_norebind(self):
        """Test that norebind option prevents overwriting an existing forward."""
        # Add a forward
        rc, out, err = await self._run_adb("forward", "tcp:6004", "tcp:7004")
        self.assertEqual(rc, 0, f"First adb forward failed: {err}")
        
        # Verify it was added
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertIn("tcp:6004", out, "Forward not found in list after adding")

        # Try to add it again with norebind
        rc, out, err = await self._run_adb("forward", "--no-rebind", "tcp:6004", "tcp:8004")
        self.assertNotEqual(rc, 0, f"adb forward --no-rebind should have failed but succeeded. stdout: {out}, stderr: {err}")
        self.assertIn("cannot rebind existing socket", err)

        # Verify original forward is still there
        rc, out, err = await self._run_adb("forward", "--list")
        self.assertIn("test-5554 tcp:6004 tcp:7004", out)
        self.assertNotIn("tcp:8004", out)
