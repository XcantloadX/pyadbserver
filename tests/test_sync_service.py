import asyncio
import os
import sys
import tempfile
from typing import List, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pyadbserver.services import SyncV1Service, MemoryFileSystem
from tests.base_test import AdbServerTestCase
from pyadbserver.transport.device_manager import SingleDeviceService


class TestSyncService(AdbServerTestCase):
    def get_services(self, device_manager: SingleDeviceService) -> List[Any]:
        """Register the SyncV1Service with a MemoryFileSystem."""
        self.memory_fs = MemoryFileSystem(auto_create=True)
        return [SyncV1Service(self.memory_fs)]
    
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The base class setup calls start_server, which calls get_services.
        # So self.memory_fs is now available.
        self.fs = self.memory_fs

    async def test_push_pull(self):
        # In a temporary directory, create a test file
        local_file = os.path.join(self.tmpdir, "test_file.txt")
        test_content = b"Hello from ADB test!\n" * 100
        with open(local_file, "wb") as f:
            f.write(test_content)
        
        # Use adb push to send the file to the server (MemoryFileSystem)
        remote_path = "/data/test_file.txt"
        rc, out, err = await self._run_adb("push", local_file, remote_path, timeout=30)
        self.assertEqual(rc, 0, f"adb push failed: {err}\nstdout: {out}")
        
        # Verify the file exists in MemoryFileSystem
        try:
            stat = self.fs.stat("data/test_file.txt")
            self.assertEqual(stat.size, len(test_content))
        except Exception as e:
            self.fail(f"File not found in MemoryFileSystem: {e}")
        
        # Use adb pull to retrieve the file from the server
        pulled_file = os.path.join(self.tmpdir, "pulled_file.txt")
        rc, out, err = await self._run_adb("pull", remote_path, pulled_file, timeout=30)
        self.assertEqual(rc, 0, f"adb pull failed: {err}\nstdout: {out}")
        
        # Verify the content of the pulled file
        with open(pulled_file, "rb") as f:
            pulled_content = f.read()
        self.assertEqual(pulled_content, test_content)
    
    async def test_push_to_memory_pull_verify(self):
        """Test pushing multiple files to the memory filesystem and verifying them."""
        files_to_test = {
            "small.txt": b"small content",
            "large.bin": b"\x00\xFF" * 10000,
            "unicode.txt": "中文测试内容 🎉".encode("utf-8"),
        }
        
        for filename, content in files_to_test.items():
            # Create local file
            local_file = os.path.join(self.tmpdir, filename)
            with open(local_file, "wb") as f:
                f.write(content)
            
            # push to server
            remote_path = f"/data/{filename}"
            rc, out, err = await self._run_adb("push", local_file, remote_path, timeout=30)
            self.assertEqual(rc, 0, f"Failed to push {filename}: {err}\nstdout: {out}")
            
            # Read from MemoryFileSystem and verify
            with self.fs.open_for_read(f"data/{filename}") as f:
                mem_content = f.read()
            self.assertEqual(mem_content, content, f"Content mismatch for {filename}")


