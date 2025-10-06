from __future__ import annotations

import io
import os
import stat
import time
from dataclasses import dataclass
from typing import BinaryIO, Dict, Iterable, Optional, Union


@dataclass
class FileStat:
    mode: int
    size: int
    mtime: int


@dataclass
class Dirent:
    name: str
    mode: int
    size: int
    mtime: int


class AbstractFileSystem:
    """Abstract file system interface for SyncService.

    Implementations can integrate custom backends (local disk, memory, object storage, etc.).
    Potentially blocking file operations should be executed by the caller in a thread pool.
    """

    def stat(self, path: str) -> FileStat:
        raise NotImplementedError

    def iterdir(self, path: str) -> Iterable[Dirent]:
        raise NotImplementedError

    def open_for_read(self, path: str) -> BinaryIO:
        raise NotImplementedError

    def open_for_write(self, path: str, mode: int) -> BinaryIO:
        raise NotImplementedError

    def set_mtime(self, path: str, mtime: int) -> None:
        raise NotImplementedError

    def makedirs(self, path: str) -> None:
        raise NotImplementedError


class LocalFileSystem(AbstractFileSystem):
    """Local disk-based file system implementation.

    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base_dir = base_dir if base_dir is not None else os.getcwd()

    def _resolve(self, path: str) -> str:
        # Remove leading separators to join under base_dir, preserve .. semantics, no sandboxing
        if os.path.isabs(path):
            path = path.lstrip("/\\")
        if self._base_dir:
            combined = os.path.join(self._base_dir, path)
        else:
            combined = path
        return os.path.normpath(combined)

    def stat(self, path: str) -> FileStat:
        p = self._resolve(path)
        st = os.stat(p)
        return FileStat(mode=st.st_mode, size=int(st.st_size), mtime=int(st.st_mtime))

    def iterdir(self, path: str) -> Iterable[Dirent]:
        p = self._resolve(path)
        with os.scandir(p) as it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                    yield Dirent(name=entry.name, mode=st.st_mode, size=int(st.st_size), mtime=int(st.st_mtime))
                except FileNotFoundError:
                    # Race condition: directory entry was deleted during scan, ignore
                    continue

    def open_for_read(self, path: str) -> BinaryIO:
        p = self._resolve(path)
        return open(p, "rb")

    def open_for_write(self, path: str, mode: int) -> BinaryIO:
        # Create parent directories as needed
        p = self._resolve(path)
        parent = os.path.dirname(p)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        # Mode bits only work on *nix, ignored on Windows
        try:
            fh = open(p, "wb")
        finally:
            pass
        try:
            # Best effort to set permission bits
            try:
                os.chmod(p, mode & 0o7777)
            except Exception:
                pass
        finally:
            pass
        return fh

    def set_mtime(self, path: str, mtime: int) -> None:
        p = self._resolve(path)
        try:
            atime = os.stat(p).st_atime
        except Exception:
            atime = mtime
        os.utime(p, (atime, mtime))

    def makedirs(self, path: str) -> None:
        p = self._resolve(path)
        os.makedirs(p, exist_ok=True)


class MemoryFileSystem(AbstractFileSystem):
    """In-memory file system implementation.

    Maintains a simple file tree structure in memory, supporting file and directory
    creation, reading, and writing operations.
    Suitable for testing or temporary data storage scenarios.
    """

    class _Node:
        """Internal node class representing a file or directory."""
        def __init__(self, mode: int, mtime: int | None = None):
            self.mode = mode
            self.mtime = mtime or int(time.time())
            # For directories, children stores child nodes; for files, data stores content
            self.children: Dict[str, MemoryFileSystem._Node] | None = None
            self.data: bytes | None = None

            if stat.S_ISDIR(mode):
                self.children = {}
            else:
                self.data = b""

        @property
        def size(self) -> int:
            if self.data is not None:
                return len(self.data)
            return 0

        def is_dir(self) -> bool:
            return stat.S_ISDIR(self.mode)

        def is_file(self) -> bool:
            return stat.S_ISREG(self.mode)

    def __init__(self, *, auto_create: bool = True) -> None:
        """
        Initialize memory file system, creating the root directory.
        """
        # Root directory with mode 755
        self._root = self._Node(mode=stat.S_IFDIR | 0o755)
        self.auto_create = auto_create
        """If True, auto create missing intermediate directories when opening a file for writing."""

    def _normalize_path(self, path: str) -> str:
        """Normalize path, removing redundant slashes and . components."""
        # Convert Windows path separators
        path = path.replace("\\", "/")
        # Remove leading slashes
        path = path.lstrip("/")
        # If empty path, return "."
        if not path:
            return "."
        return path

    def _split_path(self, path: str) -> list[str]:
        """Split path into component list."""
        path = self._normalize_path(path)
        if path == ".":
            return []
        parts = path.split("/")
        # Filter out empty strings and "."
        return [p for p in parts if p and p != "."]

    def _traverse(self, path: str, create_missing: bool = False, 
                  parent_mode: int = stat.S_IFDIR | 0o755) -> _Node:
        """Traverse path and return the corresponding node.
        
        Args:
            path: Path to traverse
            create_missing: If True, create missing intermediate directories
            parent_mode: Mode to use when creating intermediate directories
            
        Returns:
            Node corresponding to the path
            
        Raises:
            FileNotFoundError: Path does not exist and create_missing=False
            NotADirectoryError: Intermediate path is not a directory
        """
        parts = self._split_path(path)
        
        if not parts:  # Root directory
            return self._root
            
        current = self._root
        
        for i, part in enumerate(parts):
            if not current.is_dir():
                raise NotADirectoryError(f"Not a directory: {'/'.join(parts[:i])}")
            
            assert current.children is not None, "Directory node must have children dict"
                
            if part not in current.children:
                if create_missing:
                    # Create intermediate directory
                    current.children[part] = self._Node(mode=parent_mode)
                else:
                    raise FileNotFoundError(f"No such file or directory: {path}")
                    
            current = current.children[part]
            
        return current

    def _get_parent(self, path: str) -> tuple[_Node, str]:
        """Get the parent directory node and filename for a path.
        
        Returns:
            Tuple of (parent directory node, filename)
            
        Raises:
            FileNotFoundError: Parent directory does not exist
        """
        parts = self._split_path(path)
        if not parts:
            raise ValueError("Cannot get parent of root")
            
        filename = parts[-1]
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else "."
        parent = self._traverse(parent_path)
        
        if not parent.is_dir():
            raise NotADirectoryError(f"Not a directory: {parent_path}")
            
        return parent, filename

    def stat(self, path: str) -> FileStat:
        """Get file or directory status information."""
        node = self._traverse(path)
        return FileStat(mode=node.mode, size=node.size, mtime=node.mtime)

    def iterdir(self, path: str) -> Iterable[Dirent]:
        """List all entries in a directory."""
        node = self._traverse(path)
        
        if not node.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        
        assert node.children is not None, "Directory node must have children dict"
            
        for name, child in node.children.items():
            yield Dirent(
                name=name,
                mode=child.mode,
                size=child.size,
                mtime=child.mtime
            )

    def open_for_read(self, path: str) -> BinaryIO:
        """Open a file for reading."""
        node = self._traverse(path)
        
        if not node.is_file():
            raise IsADirectoryError(f"Is a directory: {path}")
        
        assert node.data is not None, "File node must have data"
            
        return io.BytesIO(node.data)

    def open_for_write(self, path: str, mode: int) -> BinaryIO:
        """Open a file for writing.
        
        Returns a special BytesIO object that writes data back to the node on close.
        """
        if self.auto_create:
            self._traverse(os.path.dirname(path), create_missing=True)

        parent, filename = self._get_parent(path)
        
        assert parent.children is not None, "Parent must be a directory"
        
        # Create file if it doesn't exist
        if filename not in parent.children:
            parent.children[filename] = self._Node(mode=stat.S_IFREG | (mode & 0o777))
            node = parent.children[filename]
        else:
            node = parent.children[filename]
            if not node.is_file():
                raise IsADirectoryError(f"Is a directory: {path}")
            # Update mode
            node.mode = stat.S_IFREG | (mode & 0o777)
            
        # Create a special BytesIO that writes back data on close
        buffer = io.BytesIO()
        original_close = buffer.close
        
        def close_with_writeback():
            node.data = buffer.getvalue()
            node.mtime = int(time.time())
            original_close()
            
        buffer.close = close_with_writeback
        return buffer

    def set_mtime(self, path: str, mtime: int) -> None:
        """Set the modification time of a file or directory."""
        node = self._traverse(path)
        node.mtime = mtime

    def makedirs(self, path: str) -> None:
        """Create directory (including all necessary parent directories)."""
        # Use _traverse's create_missing feature
        try:
            self._traverse(path, create_missing=True)
        except FileNotFoundError:
            # If path already exists, _traverse returns the node without exception
            pass


