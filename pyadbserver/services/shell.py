from __future__ import annotations

import asyncio
import os
import struct
import sys
from typing import Tuple, TYPE_CHECKING
from enum import IntEnum

from ..server.routing import FAIL, device_route, route, NOOP, ResponseAction, g_session

if TYPE_CHECKING:
    from ..server.session import SmartSocketSession


# Shell Protocol v2 constants
# Reference: adb/shell_protocol.h
class ShellProtocolId(IntEnum):
    STDIN = 0
    STDOUT = 1
    STDERR = 2
    EXIT = 3
    CLOSE_STDIN = 4
    WINDOW_SIZE_CHANGE = 5
    INVALID = 255


# Shell Protocol v2 包格式: [1字节ID][4字节长度(little-endian)][数据]
SHELL_PROTOCOL_HEADER_SIZE = 5


def encode_shell_packet(packet_id: ShellProtocolId, data: bytes = b"") -> bytes:
    length = len(data)
    # Format: B=uint8, I=uint32 (little-endian)
    header = struct.pack("<BI", packet_id, length)
    return header + data


def decode_shell_packet_header(header: bytes) -> Tuple[ShellProtocolId, int]:
    packet_id, length = struct.unpack("<BI", header)
    return ShellProtocolId(packet_id), length


class LocalShellService:
    """Local shell service implementation (non-interactive only)
    
    Supports:
    - Non-interactive shell commands
    - Shell Protocol v2 (separate stdout/stderr, exit codes)
    - exec commands (raw mode)
    """

    @device_route("shell:")
    async def shell_interactive(self):
        return FAIL("interactive shell is not supported")

    @device_route("shell:<cmd>")
    async def shell_run(self, cmd: str):
        """Non-interactive shell command (without protocol)"""
        return await self._run_shell_command(cmd, use_protocol=False, use_pty=False)

    @device_route("shell,v2:")
    async def shell_v2_interactive(self):
        return FAIL("interactive shellv2 is not supported")

    @device_route("shell,v2:<cmd>")
    async def shell_v2_run(self, cmd: str):
        """Non-interactive shell command (using shell protocol v2)"""
        return await self._run_shell_command(cmd, use_protocol=True, use_pty=False)

    @device_route("exec:<cmd>")
    async def exec_run(self, cmd: str):
        return FAIL("exec command is not supported")

    # ===== Core Implementation =====

    async def _run_shell_command(
        self, 
        cmd: str, 
        use_protocol: bool, 
        use_pty: bool
    ):
        """
        Run non-interactive shell command
        
        Args:
            cmd: Command to execute
            use_protocol: Whether to use shell protocol v2
            use_pty: Whether to use PTY (usually not needed for non-interactive)
        """
        session = g_session.get()

        # Send OKAY to accept command
        await session.send_okay(flush=True)

        # Select shell based on platform
        shell = self._get_shell_executable()
        shell_arg = self._get_shell_arg()

        if use_pty:
            # PTY mode (not fully implemented yet, requires pty library)
            # On Windows PTY support is poor, recommend using raw mode
            session.write(b"PTY mode not fully implemented\n")
            await session._flush()
            return NOOP(action=ResponseAction.CLOSE)

        # Create subprocess (raw mode)
        # For non-interactive commands, stdin should be closed or set to DEVNULL
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,  # Non-interactive, no stdin
            shell=True,
            executable=shell,
        )
        
        # Note: stdin is explicitly set to DEVNULL for non-interactive commands
        # to prevent blocking on commands that might read from stdin

        if use_protocol:
            # Use shell protocol v2: separate stdout/stderr and send exit code
            await self._handle_protocol_subprocess(session, proc)
        else:
            # Without protocol: merge stdout/stderr, no exit code
            await self._handle_raw_subprocess(session, proc)

        return NOOP(action=ResponseAction.CLOSE)

    # ===== Protocol Handlers =====

    async def _handle_protocol_subprocess(self, session: 'SmartSocketSession', proc: asyncio.subprocess.Process):
        """Handle subprocess using shell protocol (non-interactive)"""
        
        async def read_stdout():
            """Read stdout and send via protocol"""
            if proc.stdout:
                try:
                    while True:
                        # Use 8KB buffer for non-interactive commands
                        chunk = await proc.stdout.read(8192)
                        if not chunk:
                            break
                        packet = encode_shell_packet(ShellProtocolId.STDOUT, chunk)
                        session.write(packet)
                        await session._flush()
                except Exception:
                    pass

        async def read_stderr():
            """Read stderr and send via protocol"""
            if proc.stderr:
                try:
                    while True:
                        # Use 8KB buffer for non-interactive commands
                        chunk = await proc.stderr.read(8192)
                        if not chunk:
                            break
                        packet = encode_shell_packet(ShellProtocolId.STDERR, chunk)
                        session.write(packet)
                        await session._flush()
                except Exception:
                    pass

        # Read stdout and stderr concurrently
        await asyncio.gather(read_stdout(), read_stderr())

        # Wait for process to exit
        exit_code = await proc.wait()

        # Send exit code
        # Exit code is sent as 1 byte of data
        exit_data = struct.pack("B", exit_code & 0xFF)
        exit_packet = encode_shell_packet(ShellProtocolId.EXIT, exit_data)
        session.write(exit_packet)
        await session._flush()

    async def _handle_raw_subprocess(self, session: 'SmartSocketSession', proc: asyncio.subprocess.Process):
        """Handle subprocess without protocol (non-interactive)"""
        
        async def forward_output():
            """Forward stdout (stderr redirected to stdout)"""
            if proc.stdout:
                try:
                    while True:
                        # Use 8KB buffer for non-interactive commands
                        chunk = await proc.stdout.read(8192)
                        if not chunk:
                            break
                        session.write(chunk)
                        await session._flush()
                except Exception:
                    pass
            
            # If stderr exists separately
            if proc.stderr:
                try:
                    while True:
                        chunk = await proc.stderr.read(8192)
                        if not chunk:
                            break
                        session.write(chunk)
                        await session._flush()
                except Exception:
                    pass

        await forward_output()
        await proc.wait()
        # Raw mode does not send exit code

    # ===== Utility Methods =====

    def _get_shell_executable(self) -> str:
        """Get shell executable for current platform"""
        if sys.platform == "win32":
            # Windows: use PowerShell or cmd
            # Prefer PowerShell for better experience
            return os.environ.get("COMSPEC", "cmd.exe")
        else:
            # Unix/Linux/macOS: use user's default shell
            return os.environ.get("SHELL", "/bin/sh")

    def _get_shell_arg(self) -> str:
        """Get shell command argument flag"""
        if sys.platform == "win32":
            return "/c"  # cmd.exe uses /c to execute command
        else:
            return "-c"  # Unix shell uses -c to execute command
