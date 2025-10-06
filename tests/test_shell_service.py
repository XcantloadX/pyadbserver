"""Shell service tests

Tests for various shell service modes and protocol functionality
"""

import asyncio
import struct
import sys
import os
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyadbserver.services.shell import (
    ShellProtocolId,
    encode_shell_packet,
    decode_shell_packet_header,
)


class TestShellProtocol(unittest.TestCase):
    """Test Shell Protocol v2 encoding and decoding"""

    def test_encode_stdout_packet(self):
        """Test encoding stdout packet"""
        data = b"Hello, World!"
        packet = encode_shell_packet(ShellProtocolId.STDOUT, data)
        
        # Verify packet header
        self.assertEqual(len(packet), 5 + len(data))
        self.assertEqual(packet[0], ShellProtocolId.STDOUT)
        
        # Verify length field (little-endian)
        length = struct.unpack("<I", packet[1:5])[0]
        self.assertEqual(length, len(data))
        
        # Verify data
        self.assertEqual(packet[5:], data)

    def test_encode_stderr_packet(self):
        """Test encoding stderr packet"""
        data = b"Error message"
        packet = encode_shell_packet(ShellProtocolId.STDERR, data)
        
        self.assertEqual(packet[0], ShellProtocolId.STDERR)
        self.assertEqual(packet[5:], data)

    def test_encode_exit_packet(self):
        """Test encoding exit code packet"""
        exit_code = 42
        exit_data = struct.pack("B", exit_code)
        packet = encode_shell_packet(ShellProtocolId.EXIT, exit_data)
        
        self.assertEqual(packet[0], ShellProtocolId.EXIT)
        self.assertEqual(len(packet), 5 + 1)
        self.assertEqual(packet[5], exit_code)

    def test_encode_empty_packet(self):
        """Test encoding empty packet"""
        packet = encode_shell_packet(ShellProtocolId.CLOSE_STDIN)
        
        self.assertEqual(len(packet), 5)
        self.assertEqual(packet[0], ShellProtocolId.CLOSE_STDIN)
        length = struct.unpack("<I", packet[1:5])[0]
        self.assertEqual(length, 0)

    def test_decode_packet_header(self):
        """Test decoding packet header"""
        # Create a test packet
        data = b"test data"
        packet = encode_shell_packet(ShellProtocolId.STDOUT, data)
        
        # Decode header
        packet_id, length = decode_shell_packet_header(packet[:5])
        
        self.assertEqual(packet_id, ShellProtocolId.STDOUT)
        self.assertEqual(length, len(data))

    def test_roundtrip_encoding(self):
        """Test encode-decode roundtrip"""
        original_data = b"Round trip test data"
        
        # Encode
        packet = encode_shell_packet(ShellProtocolId.STDOUT, original_data)
        
        # Decode header
        packet_id, length = decode_shell_packet_header(packet[:5])
        
        # Extract data
        decoded_data = packet[5:5+length]
        
        self.assertEqual(packet_id, ShellProtocolId.STDOUT)
        self.assertEqual(decoded_data, original_data)

    def test_large_packet(self):
        """Test large packet (4KB)"""
        large_data = b"x" * 4096
        packet = encode_shell_packet(ShellProtocolId.STDOUT, large_data)
        
        packet_id, length = decode_shell_packet_header(packet[:5])
        self.assertEqual(packet_id, ShellProtocolId.STDOUT)
        self.assertEqual(length, 4096)
        self.assertEqual(packet[5:], large_data)


class TestShellService(unittest.TestCase):
    """Test shell service functionality (integration tests)"""

    def test_shell_command_basic(self):
        """Test basic shell command execution"""
        # TODO: Requires actual server and client for testing
        # This is a placeholder test
        pass

    def test_shell_v2_command(self):
        """Test shell v2 command execution"""
        # TODO: Requires actual server and client for testing
        pass

    def test_interactive_shell(self):
        """Test interactive shell"""
        # TODO: Requires actual server and client for testing
        pass


def print_manual_tests():
    """Manual testing tool for protocol encoding/decoding"""
    
    print("=== Shell Protocol v2 Encoding/Decoding Tests ===\n")
    
    # Test 1: STDOUT packet
    print("1. Test STDOUT packet:")
    data = b"Hello from stdout"
    packet = encode_shell_packet(ShellProtocolId.STDOUT, data)
    print(f"   Original data: {data}")
    print(f"   Encoded (hex): {packet.hex()}")
    packet_id, length = decode_shell_packet_header(packet[:5])
    print(f"   Decoded: ID={packet_id}, Length={length}")
    print(f"   Data: {packet[5:]}\n")
    
    # Test 2: STDERR packet
    print("2. Test STDERR packet:")
    data = b"Error message"
    packet = encode_shell_packet(ShellProtocolId.STDERR, data)
    print(f"   Original data: {data}")
    print(f"   Encoded (hex): {packet.hex()}")
    packet_id, length = decode_shell_packet_header(packet[:5])
    print(f"   Decoded: ID={packet_id}, Length={length}\n")
    
    # Test 3: EXIT packet
    print("3. Test EXIT packet (exit code=0):")
    exit_data = struct.pack("B", 0)
    packet = encode_shell_packet(ShellProtocolId.EXIT, exit_data)
    print(f"   Encoded (hex): {packet.hex()}")
    packet_id, length = decode_shell_packet_header(packet[:5])
    exit_code = packet[5]
    print(f"   Decoded: ID={packet_id}, ExitCode={exit_code}\n")
    
    # Test 4: CLOSE_STDIN packet
    print("4. Test CLOSE_STDIN packet:")
    packet = encode_shell_packet(ShellProtocolId.CLOSE_STDIN)
    print(f"   Encoded (hex): {packet.hex()}")
    packet_id, length = decode_shell_packet_header(packet[:5])
    print(f"   Decoded: ID={packet_id}, Length={length}\n")
    
    print("=== All tests completed ===")


if __name__ == "__main__":
    # Run manual tests if executed directly
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        print_manual_tests()
    else:
        # Run unittest
        unittest.main()
