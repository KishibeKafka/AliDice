# -*- coding: utf-8 -*-
"""AliDice 历史存储：只追加的二进制日志 + HMAC 链校验。

不可篡改的三道防线
------------------
1. **结构 + 校验链**：每条记录带序号、上一记录的 MAC 与自身 MAC。
   修改任意字节、删除中间记录、调换顺序、从别的历史文件里拼接记录，
   都会在打开历史时被发现。
2. **只追加句柄**：落盘走 Windows 的 ``FILE_APPEND_DATA`` 句柄（不含
   ``GENERIC_WRITE``），句柄本身没有覆盖写权限，程序代码也不可能改写
   已写入的字节；打开期间以"拒绝写入"方式共享，其它进程同样写不进去。
3. **密钥外置 + 机器绑定**：MAC 密钥由随机 secret（存放在
   ``%LOCALAPPDATA%\\AliDice``）与机器指纹派生，不在数据目录里；
   额外的 seal 文件记录"条数 + 链头"，用来发现链式校验本身
   看不出来的"截断尾部"改动。

文件布局（小端）::

    文件头 32B:  magic(8) version(2) flags(2) file_id(16) reserved(4)
    记录  :  头 64B | payload | tag 32B
    记录头:  magic(4) index(4) payload_len(4) ts_ms(8) version(2)
             reserved(10) prev_tag(32)
    tag   :  HMAC(key, "REC" | file_id | 记录头 | payload)
    payload: notation_len(1) notation | roll_count(4) modifier(4)
             total(8) | rolls(i32 × n)
    seal 96B: magic(8) version(2) reserved(2) count(4) file_id(16)
              head_tag(32) mac(32)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "Record",
    "Report",
    "HistoryStore",
    "HistoryError",
    "TamperDetected",
    "STATE_OK",
    "STATE_EMPTY",
    "STATE_TAMPERED",
    "STATE_UNVERIFIABLE",
]

# ---------------------------------------------------------------- 常量

FILE_MAGIC = b"ALIDICE1"
FILE_VERSION = 1
FILE_HEADER_FMT = "<8sHH16s4s"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FMT)  # 32

REC_MAGIC = b"REC\x00"
REC_VERSION = 1
REC_HEADER_FMT = "<4sIIQH10s32s"
REC_HEADER_SIZE = struct.calcsize(REC_HEADER_FMT)  # 64
REC_TAIL_FMT = "<IiQ"
REC_TAIL_SIZE = struct.calcsize(REC_TAIL_FMT)  # 16

TAG_SIZE = 32
ZERO_TAG = b"\x00" * TAG_SIZE

SEAL_MAGIC = b"ALIDSEAL"
SEAL_VERSION = 1
SEAL_FMT = "<8sHHI16s32s32s"
SEAL_SIZE = struct.calcsize(SEAL_FMT)  # 96

MAX_PAYLOAD = 512 * 1024
MAX_ROLLS = 4000
MAX_NOTATION = 200
MAX_SIDES = 1_000_000_000

STATE_OK = "ok"
STATE_EMPTY = "empty"
STATE_TAMPERED = "tampered"
STATE_UNVERIFIABLE = "unverifiable"


class HistoryError(Exception):
    """历史读写失败。"""


class TamperDetected(HistoryError):
    """校验链不成立。"""


# ---------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Record:
    index: int
    timestamp_ms: int
    notation: str
    rolls: Tuple[int, ...]
    modifier: int
    total: int
    tag: bytes = b""
    verified: bool = True

    @property
    def timestamp(self) -> float:
        return self.timestamp_ms / 1000.0

    @property
    def time_text(self) -> str:
        return time.strftime("%m-%d %H:%M:%S", time.localtime(self.timestamp))

    @property
    def short_time(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.timestamp))

    @property
    def clock_text(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))

    @property
    def rolls_text(self) -> str:
        return " · ".join(str(r) for r in self.rolls)

    @property
    def short_tag(self) -> str:
        return self.tag.hex()[:16] if self.tag else "-"


@dataclass
class Report:
    state: str = STATE_EMPTY
    message: str = ""
    record_count: int = 0
    head_tag: bytes = ZERO_TAG
    notes: Tuple[str, ...] = ()

    @property
    def can_append(self) -> bool:
        return self.state in (STATE_OK, STATE_EMPTY)

    @property
    def ok(self) -> bool:
        return self.can_append

    @property
    def head_text(self) -> str:
        return self.head_tag.hex()[:16] if self.head_tag != ZERO_TAG else "-"


# ---------------------------------------------------------------- 平台辅助


def project_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_data_dir() -> str:
    return os.path.join(project_dir(), "data")


def key_dir() -> str:
    """密钥/seal 的存放目录，刻意放在数据目录之外。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
    return os.path.join(base, "AliDice")


def machine_fingerprint() -> bytes:
    """机器指纹：把密钥绑定到当前机器/系统安装。"""
    parts = [platform.system(), platform.machine()]
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as k:
                parts.append(str(winreg.QueryValueEx(k, "MachineGuid")[0]))
        elif sys.platform == "darwin":
            import subprocess

            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts.append(line.split("=")[-1].strip().strip('"'))
                    break
        else:
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        parts.append(fh.read().strip())
                    break
                except OSError:
                    continue
    except Exception:
        pass
    if len(parts) == 2:  # 没拿到系统 ID 时退回 MAC 地址
        parts.append(str(uuid.getnode()))
    return hashlib.sha256("|".join(parts).encode("utf-8")).digest()


def _hide_file(path: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes

            FILE_ATTRIBUTE_HIDDEN = 0x2
            ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN)
        else:
            os.chmod(path, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------------- 只追加写


class _AppendWriter:
    """只能追加、不能覆盖的写句柄。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._win = False
        self._handle = None
        self._fd = None
        if sys.platform == "win32" and _K32 is not None:
            try:
                self._open_win()
                self._win = True
                return
            except OSError:
                self._handle = None
        self._fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)

    def _open_win(self) -> None:
        # GENERIC_READ 仅用于 GetFileSize；写权限只有 FILE_APPEND_DATA，
        # 因此这个句柄在系统层面就无法改写已有字节。
        access = _GENERIC_READ | _FILE_APPEND_DATA
        share = _FILE_SHARE_READ  # 不允许其它进程写入/删除
        handle = _K32.CreateFileW(
            self.path, access, share, None, _OPEN_ALWAYS, _FILE_ATTRIBUTE_NORMAL, None
        )
        if not handle or handle == _INVALID_HANDLE:
            raise OSError("CreateFileW 失败，无法打开只追加句柄")
        self._handle = handle

    def write(self, data: bytes) -> None:
        if self._win:
            written = _DWORD(0)
            if not _K32.WriteFile(
                self._handle, data, len(data), _byref(written), None
            ):
                raise HistoryError("写入历史文件失败")
            if written.value != len(data):
                raise HistoryError("写入历史文件不完整")
        else:
            view = memoryview(data)
            while view:
                n = os.write(self._fd, view)
                view = view[n:]

    def flush(self) -> None:
        if self._win:
            _K32.FlushFileBuffers(self._handle)
        else:
            os.fsync(self._fd)

    def size(self) -> int:
        if self._win:
            value = _ULONGLONG(0)
            if not _K32.GetFileSizeEx(self._handle, _byref(value)):
                raise HistoryError("读取历史文件大小失败")
            return int(value.value)
        return os.fstat(self._fd).st_size

    def read_tail(self, n: int) -> bytes:
        """用写句柄读回末尾 n 字节（用于写入后自检）。"""
        if self._win:
            size = self.size()
            if size < n:
                return b""
            new_pos = _ULONGLONG(0)
            if not _K32.SetFilePointerEx(self._handle, _ULONGLONG(size - n), _byref(new_pos), 0):
                return b""
            buf = ctypes.create_string_buffer(n)
            read = _DWORD(0)
            if not _K32.ReadFile(self._handle, buf, n, _byref(read), None):
                return b""
            return buf.raw[: read.value]
        try:
            with open(self.path, "rb") as fh:
                fh.seek(-n, os.SEEK_END)
                return fh.read(n)
        except OSError:
            return b""

    def close(self) -> None:
        if self._win and self._handle:
            _K32.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


# Windows API 绑定（失败则退回普通 O_APPEND）
_K32 = None
_DWORD = _byref = _ULONGLONG = None
_INVALID_HANDLE = 0
_GENERIC_READ = 0x80000000
_FILE_APPEND_DATA = 0x00000004
_FILE_SHARE_READ = 0x00000001
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x00000080

if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes

        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _K32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        _K32.CreateFileW.restype = ctypes.c_void_p
        _K32.WriteFile.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        _K32.WriteFile.restype = wintypes.BOOL
        _K32.ReadFile.argtypes = [
            ctypes.c_void_p,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        _K32.ReadFile.restype = wintypes.BOOL
        _K32.SetFilePointerEx.argtypes = [
            ctypes.c_void_p,
            wintypes.LARGE_INTEGER,
            ctypes.POINTER(wintypes.LARGE_INTEGER),
            wintypes.DWORD,
        ]
        _K32.SetFilePointerEx.restype = wintypes.BOOL
        _K32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
        _K32.FlushFileBuffers.restype = wintypes.BOOL
        _K32.GetFileSizeEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LARGE_INTEGER)]
        _K32.GetFileSizeEx.restype = wintypes.BOOL
        _K32.CloseHandle.argtypes = [ctypes.c_void_p]
        _K32.CloseHandle.restype = wintypes.BOOL
        _DWORD = wintypes.DWORD
        _ULONGLONG = wintypes.LARGE_INTEGER  # c_longlong，与 GetFileSizeEx 签名匹配
        _byref = ctypes.byref
        _INVALID_HANDLE = ctypes.c_void_p(-1).value
    except Exception:  # pragma: no cover - 环境不支持则退回普通追加
        _K32 = None


# ---------------------------------------------------------------- 打包/校验


def _mac(key: bytes, *parts: bytes) -> bytes:
    h = hmac.new(key, digestmod=hashlib.sha256)
    for part in parts:
        h.update(len(part).to_bytes(4, "little"))
        h.update(part)
    return h.digest()


def _encode_payload(
    notation: str, rolls: Sequence[int], modifier: int, total: int
) -> bytes:
    nb = notation.encode("utf-8")
    if len(nb) > MAX_NOTATION:
        raise HistoryError("表达式过长，无法写入历史")
    if len(rolls) > MAX_ROLLS:
        raise HistoryError("骰子数量过多，无法写入历史")
    head = struct.pack("<B", len(nb)) + nb + struct.pack(REC_TAIL_FMT, len(rolls), modifier, total)
    return head + struct.pack(f"<{len(rolls)}i", *rolls)


def _decode_payload(payload: bytes) -> Tuple[str, Tuple[int, ...], int, int]:
    if len(payload) < 1:
        raise ValueError("payload 为空")
    nlen = payload[0]
    pos = 1
    if len(payload) < pos + nlen + REC_TAIL_SIZE:
        raise ValueError("payload 被截断")
    notation = payload[pos : pos + nlen].decode("utf-8")
    pos += nlen
    count, modifier, total = struct.unpack(REC_TAIL_FMT, payload[pos : pos + REC_TAIL_SIZE])
    pos += REC_TAIL_SIZE
    if count > MAX_ROLLS:
        raise ValueError("点数数量越界")
    end = pos + count * 4
    if len(payload) != end:
        raise ValueError("payload 长度不匹配")
    rolls = struct.unpack(f"<{count}i", payload[pos:end]) if count else ()
    for value in rolls:
        if not 1 <= value <= MAX_SIDES:
            raise ValueError("点数越界")
    if sum(rolls) + modifier != total:
        raise ValueError("合计与点数不一致")
    return notation, tuple(rolls), modifier, total


# ---------------------------------------------------------------- 存储主体


class HistoryStore:
    """历史记录存储。``open()`` 之后通过 :attr:`records` / :attr:`report` 访问。"""

    FILE_NAME = "history.dat"
    SEAL_NAME = "seal.bin"
    SECRET_NAME = "secret.bin"

    def __init__(
        self,
        data_dir: Optional[str] = None,
        key_path: Optional[str] = None,
        read_only: bool = False,
    ) -> None:
        self.read_only = read_only
        self.data_dir = data_dir or default_data_dir()
        self.path = os.path.join(self.data_dir, self.FILE_NAME)
        self.key_dir = key_path or key_dir()
        self.secret_path = os.path.join(self.key_dir, self.SECRET_NAME)
        self.seal_path = os.path.join(self.key_dir, self.SEAL_NAME)

        self._lock = threading.RLock()
        self._writer: Optional[_AppendWriter] = None
        self._key = b""
        self._file_id = b""
        self._head_tag = ZERO_TAG
        self._seal_corrupt = False
        self.records: List[Record] = []
        self.report = Report()
        self._total_size = 0

    @classmethod
    def for_file(
        cls, path: str, read_only: bool = True, key_path: Optional[str] = None
    ) -> "HistoryStore":
        """打开任意一个历史文件（例如归档的 history-*.dat），默认只读。"""
        path = os.path.abspath(path)
        store = cls(
            data_dir=os.path.dirname(path) or ".", key_path=key_path, read_only=read_only
        )
        store.path = path
        return store

    # ------------------------------------------------------------ 密钥

    def _load_secret(self) -> None:
        os.makedirs(self.key_dir, exist_ok=True)
        secret = None
        if os.path.exists(self.secret_path):
            try:
                with open(self.secret_path, "rb") as fh:
                    blob = fh.read()
                if len(blob) == 32:
                    secret = blob
            except OSError:
                secret = None
        if secret is None:
            secret = os.urandom(32)
            tmp = self.secret_path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(secret)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.secret_path)
            _hide_file(self.secret_path)
        self._key = _mac(secret, b"alidice.mackey.v1", machine_fingerprint())

    # ------------------------------------------------------------ 打开/校验

    def open(self) -> Report:
        with self._lock:
            self._close_writer()
            os.makedirs(self.data_dir, exist_ok=True)
            self._load_secret()
            self.records = []
            self._file_id = b""
            self._head_tag = ZERO_TAG
            self._seal_corrupt = False

            notes: List[str] = []
            problems: List[str] = []

            # 当前链的锚：key 目录下的 seal.bin，用于发现"数据文件被删除"。
            anchor = self._read_seal_file(self.seal_path)
            if anchor == "corrupt":
                self._seal_corrupt = True

            data = b""
            if os.path.exists(self.path):
                try:
                    with open(self.path, "rb") as fh:
                        data = fh.read()
                except OSError as exc:
                    problems.append(f"无法读取历史文件：{exc}")

            if not data and not problems:
                if isinstance(anchor, dict) and anchor["count"] > 0:
                    self.report = Report(
                        STATE_TAMPERED,
                        "历史文件被删除或被清空（seal 中仍有记录）",
                        0,
                        ZERO_TAG,
                        ("可把当前目录归档后重新开始新的校验链",),
                    )
                    return self.report
                elif self.read_only:
                    problems.append("历史文件不存在")
                else:
                    # 首次运行：沿用 seal 里的 file_id（若 seal 表明本来就是空历史）
                    self._create_file(
                        anchor["file_id"] if isinstance(anchor, dict) else None
                    )
                    data = self._read_all()
                    anchor = self._read_seal_file(self.seal_path)

            if not data:
                if not problems:
                    problems.append("无法创建历史文件")
                self.report = Report(
                    STATE_TAMPERED, problems[0], 0, ZERO_TAG, tuple(problems)
                )
                return self.report

            if len(data) < FILE_HEADER_SIZE:
                problems.append("文件头不完整")
                self.report = Report(
                    STATE_TAMPERED, problems[0], 0, ZERO_TAG, tuple(problems)
                )
                return self.report

            magic, version, _flags, file_id, _reserved = struct.unpack(
                FILE_HEADER_FMT, data[:FILE_HEADER_SIZE]
            )
            if magic != FILE_MAGIC:
                problems.append("文件头标识不正确（不是 AliDice 历史文件）")
            elif version != FILE_VERSION:
                problems.append(f"不支持的历史文件版本：{version}")
            else:
                self._file_id = file_id

            if self._file_id:
                self._parse_records(data, problems, notes)
            self._total_size = len(data)

            seal = self._read_seal(self._file_id) if self._file_id else anchor
            self._merge_seal(seal, problems, notes)

            count = len(self.records)
            verified_records = [r for r in self.records if r.verified]
            head = verified_records[-1].tag if verified_records else ZERO_TAG
            self._head_tag = head

            if problems:
                state = STATE_UNVERIFIABLE if self._is_key_mismatch(problems) else STATE_TAMPERED
                message = problems[0]
                if state == STATE_UNVERIFIABLE:
                    message = "无法校验历史（密钥/机器指纹不匹配）"
                self.report = Report(state, message, count, head, tuple(notes + problems))
                self._close_writer()
            else:
                if count and not self.read_only:
                    self._seal(count, head)
                self.report = Report(
                    STATE_OK if count else STATE_EMPTY,
                    "历史校验通过" if count else "历史为空",
                    count,
                    head,
                    tuple(notes),
                )
                if self.read_only:
                    return self.report
                try:
                    self._open_writer()
                except HistoryError as exc:
                    self.report = Report(
                        STATE_TAMPERED, f"无法打开只追加句柄：{exc}", count, head, tuple(notes)
                    )
            return self.report

    def _is_key_mismatch(self, problems: Sequence[str]) -> bool:
        return any("首条记录" in p for p in problems)

    def _read_all(self) -> bytes:
        try:
            with open(self.path, "rb") as fh:
                return fh.read()
        except OSError:
            return b""

    def _create_file(self, file_id: Optional[bytes] = None) -> None:
        file_id = file_id or os.urandom(16)
        self._file_id = file_id
        header = struct.pack(
            FILE_HEADER_FMT, FILE_MAGIC, FILE_VERSION, 0, file_id, b"\x00\x00\x00\x00"
        )
        with open(self.path, "wb") as fh:
            fh.write(header)
            fh.flush()
            os.fsync(fh.fileno())
        # 新文件：旧锚作废，避免旧 seal 影响新链
        try:
            if os.path.exists(self.seal_path):
                os.remove(self.seal_path)
        except OSError:
            pass
        self._seal(0, ZERO_TAG)

    def _parse_records(self, data: bytes, problems: List[str], notes: List[str]) -> None:
        pos = FILE_HEADER_SIZE
        expected = 0
        prev = ZERO_TAG
        while pos < len(data):
            if len(data) - pos < REC_HEADER_SIZE:
                problems.append(f"第 {expected + 1} 条记录头不完整（文件尾部被破坏）")
                return
            header = data[pos : pos + REC_HEADER_SIZE]
            magic, index, plen, ts, version, _reserved, prev_tag = struct.unpack(
                REC_HEADER_FMT, header
            )
            if magic != REC_MAGIC:
                problems.append(f"第 {expected + 1} 条记录标识错误，文件已被改动")
                return
            if plen > MAX_PAYLOAD or len(data) - pos - REC_HEADER_SIZE - TAG_SIZE < plen:
                problems.append(f"第 {expected + 1} 条记录长度异常，文件已被改动")
                return
            payload_end = pos + REC_HEADER_SIZE + plen
            payload = data[pos + REC_HEADER_SIZE : payload_end]
            tag = data[payload_end : payload_end + TAG_SIZE]
            if len(tag) < TAG_SIZE:
                problems.append(f"第 {expected + 1} 条记录被截断")
                return

            try:
                notation, rolls, modifier, total = _decode_payload(payload)
            except (ValueError, UnicodeDecodeError) as exc:
                # 头部完好但内容损坏：仍然展示这一条，标记为未通过校验
                self.records.append(
                    Record(index, ts, "〈无法解析〉", (), 0, 0, tag, False)
                )
                problems.append(f"第 {expected + 1} 条记录内容损坏：{exc}")
                return

            if index != expected:
                problems.append(f"记录序号不连续（期望 {expected}，实际 {index}）")
                return
            if version != REC_VERSION:
                problems.append(f"第 {index + 1} 条记录版本不支持")
                return
            if prev_tag != prev:
                problems.append(f"第 {index + 1} 条记录的链接断开，历史被改动")
                return

            calc = _mac(self._key, b"REC", self._file_id, header, payload)
            verified = hmac.compare_digest(calc, tag)
            if not verified:
                if index == 0:
                    problems.append("首条记录 MAC 校验失败（密钥或机器指纹不匹配）")
                else:
                    problems.append(f"第 {index + 1} 条记录 MAC 校验失败，历史被改动")
                # 仍然展示已读到的内容（标记为未校验）
                self.records.append(
                    Record(index, ts, notation, rolls, modifier, total, tag, False)
                )
                return

            self.records.append(Record(index, ts, notation, rolls, modifier, total, tag, True))
            prev = tag
            pos = payload_end + TAG_SIZE
            expected += 1

    # ------------------------------------------------------------ seal

    def _seal(self, count: int, head_tag: bytes) -> bool:
        """写入该历史文件自己的 seal，并把它同步为当前链的锚（seal.bin）。"""
        if not self._file_id:
            return False
        mac = _mac(
            self._key, b"SEAL", self._file_id, struct.pack("<I", count), head_tag
        )
        blob = struct.pack(
            SEAL_FMT, SEAL_MAGIC, SEAL_VERSION, 0, count, self._file_id, head_tag, mac
        )
        ok = self._write_seal_file(self._seal_blob_path(self._file_id), blob)
        ok_anchor = self._write_seal_file(self.seal_path, blob)
        return ok and ok_anchor

    def _write_seal_file(self, path: str, blob: bytes) -> bool:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            _hide_file(path)
            return True
        except OSError:
            return False

    def _seal_blob_path(self, file_id: bytes) -> str:
        return os.path.join(self.key_dir, "seals", file_id.hex() + ".seal")

    def _read_seal_file(self, path: str):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except OSError:
            return None
        if len(blob) != SEAL_SIZE:
            return "corrupt"
        magic, version, _r, count, file_id, head_tag, mac = struct.unpack(SEAL_FMT, blob)
        if magic != SEAL_MAGIC or version != SEAL_VERSION:
            return "corrupt"
        calc = _mac(self._key, b"SEAL", file_id, struct.pack("<I", count), head_tag)
        if not hmac.compare_digest(calc, mac):
            return "corrupt"
        return {"count": count, "file_id": file_id, "head_tag": head_tag}

    def _read_seal(self, file_id: bytes):
        """取指定历史文件的 seal：锚匹配就用锚，否则用按 file_id 存档的 seal。

        这样归档出来的 history-*.dat 也能用 verify.py 独立校验。
        """
        anchor = self._read_seal_file(self.seal_path)
        if not file_id:
            return anchor
        if isinstance(anchor, dict) and anchor["file_id"] == file_id:
            return anchor
        return self._read_seal_file(self._seal_blob_path(file_id))

    def _merge_seal(self, seal, problems: List[str], notes: List[str]) -> None:
        verified = [r for r in self.records if r.verified]
        if seal is None:
            if verified:
                problems.append("找不到该历史文件的 seal（seal 被删除，或历史文件被替换）")
            elif self._seal_corrupt:
                problems.append("seal 校验文件损坏")
            return
        if seal == "corrupt":
            problems.append("seal 校验文件损坏")
            return
        if seal["file_id"] != self._file_id:
            problems.append("seal 与历史文件不匹配（文件被替换或被清空）")
            return
        if seal["count"] > len(verified):
            problems.append(
                f"尾部记录缺失：seal 记录 {seal['count']} 条，实际校验通过 {len(verified)} 条"
            )
            return
        if seal["count"] and (
            not verified or verified[seal["count"] - 1].tag != seal["head_tag"]
        ):
            problems.append("seal 链头与历史不一致，历史被改动")
            return
        if seal["count"] < len(verified):
            notes.append("seal 落后于数据文件（上次写入可能异常中断），已自动追平")
        if self._seal_corrupt:
            notes.append("当前 seal.bin 已损坏，本次按该历史文件自己的 seal 校验")

    # ------------------------------------------------------------ 写入

    def _open_writer(self) -> None:
        self._close_writer()
        try:
            self._writer = _AppendWriter(self.path)
        except OSError as exc:
            self._writer = None
            raise HistoryError(str(exc)) from exc

    def _close_writer(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        self._writer = None

    @property
    def can_append(self) -> bool:
        return self.report.can_append and self._writer is not None

    def append(
        self,
        notation: str,
        rolls: Sequence[int],
        modifier: int = 0,
        timestamp_ms: Optional[int] = None,
    ) -> Record:
        """追加一条记录（唯一的历史写入入口）。"""
        with self._lock:
            if not self.report.can_append:
                raise TamperDetected(self.report.message or "历史校验未通过，已锁定写入")
            if self._writer is None:
                raise HistoryError("历史文件未就绪")

            rolls = tuple(int(r) for r in rolls)
            total = sum(rolls) + modifier
            if not rolls:
                raise HistoryError("至少需要一个点数")
            payload = _encode_payload(notation, rolls, modifier, total)
            index = len(self.records)
            ts = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
            header = struct.pack(
                REC_HEADER_FMT,
                REC_MAGIC,
                index,
                len(payload),
                ts,
                REC_VERSION,
                b"\x00" * 10,
                self._head_tag,
            )
            tag = _mac(self._key, b"REC", self._file_id, header, payload)
            blob = header + payload + tag
            expected_size = self._total_size + len(blob)

            self._writer.write(blob)
            self._writer.flush()

            size = self._writer.size()
            tail = self._writer.read_tail(TAG_SIZE)
            if size != expected_size or tail != tag:
                self.report = Report(
                    STATE_TAMPERED,
                    "写入后校验失败（磁盘错误或文件被外部改动）",
                    len(self.records),
                    self._head_tag,
                    ("已锁定写入，请归档历史后重新开始",),
                )
                self._close_writer()
                raise HistoryError(self.report.message)

            record = Record(index, ts, notation, rolls, modifier, total, tag, True)
            self.records.append(record)
            self._head_tag = tag
            self._total_size = expected_size
            self._seal(len(self.records), tag)
            self.report = Report(
                STATE_OK,
                "历史校验通过",
                len(self.records),
                tag,
                self.report.notes,
            )
            return record

    def archive_and_reset(self) -> str:
        """把当前历史归档（不删除）并开启全新的校验链。返回归档文件名。"""
        with self._lock:
            self._close_writer()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archived = ""
            if os.path.exists(self.path):
                target = os.path.join(self.data_dir, f"history-{stamp}.dat")
                try:
                    os.replace(self.path, target)
                    archived = target
                except OSError as exc:
                    raise HistoryError(f"归档失败：{exc}") from exc
            try:
                if os.path.exists(self.seal_path):
                    os.replace(
                        self.seal_path,
                        os.path.join(self.key_dir, f"seal-{stamp}.bak"),
                    )
            except OSError:
                pass
            self.open()
            return archived

    def close(self) -> None:
        with self._lock:
            self._close_writer()

    def __enter__(self) -> "HistoryStore":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
