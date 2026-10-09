"""Encrypt / decrypt a Zargar machine package (scripts/export-machine.ps1) for transport, e.g. through Google Drive.

    python scripts/package_crypt.py encrypt <package-folder> <out-dir> --password-file <file>   [--part-gb 2]
    python scripts/package_crypt.py decrypt <first-part .zenc.000> <dest-dir> --password-file <file>

The folder is streamed as a tar into AES-256-GCM chunks (4 MiB each, a key from scrypt over the password); every chunk
is authenticated and numbered and the last one is flagged, so a changed, reordered or truncated part is detected.
Output is split into parts (default 2 GB) so a browser upload can be retried per part. Memory use stays a few MiB.
`encrypt` writes a new random password to --password-file when the file does not exist yet.
Needs only `cryptography` (already in the backend venv).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import secrets
import struct
import sys
import tarfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"ZARGARPKG1"
CHUNK = 4 * 1024 * 1024
N, R, P = 2 ** 17, 8, 1


def _key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=N, r=R, p=P).derive(password.encode("utf-8"))


def _nonce(base: bytes, i: int, last: bool) -> bytes:
    # 12 bytes: 7 random + 4-byte counter + 1 final flag (the flag is in the nonce, so it is authenticated)
    return base[:7] + struct.pack(">I", i) + (b"\x01" if last else b"\x00")


class _Parts:
    """A write-only file that rotates into numbered part files."""

    def __init__(self, out_dir: pathlib.Path, stem: str, part_bytes: int):
        self.dir, self.stem, self.limit = out_dir, stem, part_bytes
        self.n, self.f, self.size = -1, None, 0
        self._next()

    def _next(self):
        if self.f:
            self.f.close()
        self.n += 1
        self.f = open(self.dir / f"{self.stem}.zenc.{self.n:03d}", "wb")
        self.size = 0

    def write(self, b: bytes):
        while b:
            room = self.limit - self.size
            if room <= 0:
                self._next()
                continue
            self.f.write(b[:room])
            self.size += min(room, len(b))
            b = b[room:]

    def close(self):
        if self.f:
            self.f.close()


class _EncWriter:
    """File-like sink for tarfile: buffers plaintext and emits encrypted, length-prefixed chunks."""

    def __init__(self, sink, aes: AESGCM, base: bytes):
        self.sink, self.aes, self.base, self.buf, self.i = sink, aes, base, bytearray(), 0

    def write(self, b) -> int:
        self.buf += b
        while len(self.buf) > CHUNK:                      # strictly more: the LAST chunk is emitted by close()
            self._emit(bytes(self.buf[:CHUNK]), last=False)
            del self.buf[:CHUNK]
        return len(b)

    def _emit(self, plain: bytes, last: bool):
        ct = self.aes.encrypt(_nonce(self.base, self.i, last), plain, MAGIC)
        self.sink.write(struct.pack(">I", len(ct)) + ct)
        self.i += 1

    def close(self):
        self._emit(bytes(self.buf), last=True)
        self.buf = bytearray()

    def flush(self):
        pass


def encrypt(src: pathlib.Path, out_dir: pathlib.Path, password: str, part_gb: float) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    salt, base = os.urandom(16), os.urandom(12)
    aes = AESGCM(_key(password, salt))
    parts = _Parts(out_dir, src.name, int(part_gb * 1024 ** 3))
    parts.write(MAGIC + salt + base)
    enc = _EncWriter(parts, aes, base)
    with tarfile.open(fileobj=enc, mode="w|") as tar:
        tar.add(str(src), arcname=src.name)
    enc.close()
    parts.close()
    return sorted(out_dir.glob(f"{src.name}.zenc.*"))


class _PartsReader:
    def __init__(self, first: pathlib.Path):
        stem = first.name.rsplit(".", 1)[0]
        self.files = sorted(first.parent.glob(stem + ".*"))
        if not self.files:
            raise SystemExit(f"no parts next to {first}")
        self.k, self.f = 0, open(self.files[0], "rb")

    def read(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            b = self.f.read(n - len(out))
            if b:
                out += b
                continue
            self.f.close()
            self.k += 1
            if self.k >= len(self.files):
                break
            self.f = open(self.files[self.k], "rb")
        return out


class _DecReader:
    """File-like source for tarfile: verifies and decrypts chunk by chunk; refuses a truncated stream."""

    def __init__(self, src: _PartsReader, aes: AESGCM, base: bytes):
        self.src, self.aes, self.base, self.i, self.done = src, aes, base, 0, False
        self.buf, self.pos = b"", 0                       # current plaintext chunk + read offset (no re-copying)

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            out = [self.buf[self.pos:]]
            self.buf, self.pos = b"", 0
            while not self.done:
                out.append(self._next())
            return b"".join(out)
        out = bytearray()
        while len(out) < n:
            if self.pos >= len(self.buf):
                if self.done:
                    break
                self.buf, self.pos = self._next(), 0
                continue
            take = min(n - len(out), len(self.buf) - self.pos)
            out += self.buf[self.pos:self.pos + take]
            self.pos += take
        return bytes(out)

    def _next(self) -> bytes:
        """The next authenticated plaintext chunk (sets `done` on the flagged final chunk)."""
        hdr = self.src.read(4)
        if len(hdr) < 4:
            raise SystemExit("package is truncated (a part is missing or incomplete)")
        (ln,) = struct.unpack(">I", hdr)
        ct = self.src.read(ln)
        try:
            plain = self.aes.decrypt(_nonce(self.base, self.i, False), ct, MAGIC)
        except Exception:                                  # noqa: BLE001 - maybe the final chunk
            try:
                plain = self.aes.decrypt(_nonce(self.base, self.i, True), ct, MAGIC)
                self.done = True
            except Exception:                              # noqa: BLE001
                raise SystemExit(f"chunk {self.i} failed authentication: wrong password, or a changed part")
        self.i += 1
        return plain


def decrypt(first: pathlib.Path, dest: pathlib.Path, password: str) -> None:
    src = _PartsReader(first)
    head = src.read(len(MAGIC) + 28)
    if head[:len(MAGIC)] != MAGIC:
        raise SystemExit("not a Zargar package (bad header)")
    salt, base = head[len(MAGIC):len(MAGIC) + 16], head[len(MAGIC) + 16:]
    dec = _DecReader(src, AESGCM(_key(password, salt)), base)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=dec, mode="r|") as tar:
        tar.extractall(str(dest), filter="data")
    if not dec.done:
        dec.read()                                         # drain to the authenticated final chunk
    if not dec.done:
        raise SystemExit("package ended before its final chunk")


def _password(path: pathlib.Path, create: bool) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip().splitlines()[-1].strip()
    if not create:
        raise SystemExit(f"password file {path} not found")
    pw = secrets.token_urlsafe(24)
    path.write_text("Zargar package password - keep it in your password manager, never upload this file:\n"
                    f"{pw}\n", encoding="utf-8")
    return pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encrypt")
    e.add_argument("src")
    e.add_argument("out")
    e.add_argument("--password-file", required=True)
    e.add_argument("--part-gb", type=float, default=2.0)
    d = sub.add_parser("decrypt")
    d.add_argument("first_part")
    d.add_argument("dest")
    d.add_argument("--password-file", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "encrypt":
        pw = _password(pathlib.Path(a.password_file), create=True)
        for p in encrypt(pathlib.Path(a.src).resolve(), pathlib.Path(a.out), pw, a.part_gb):
            print(f"{p}  {p.stat().st_size / 1024 ** 3:.2f} GB")
    else:
        decrypt(pathlib.Path(a.first_part), pathlib.Path(a.dest), _password(pathlib.Path(a.password_file), create=False))
        print(f"decrypted into {a.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
