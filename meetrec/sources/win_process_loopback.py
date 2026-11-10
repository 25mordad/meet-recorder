"""Windows: capture the audio of one process tree (e.g. Chrome) with WASAPI process loopback.

Uses ActivateAudioInterfaceAsync on the virtual device "VAD\\Process_Loopback"
(Windows 10 2004 / build 19041 or later). The capture follows the process, not an
output device, so plugging in or switching headphones mid-meeting does not break it,
and system sounds from other apps (notifications etc.) are not recorded.

Pure ctypes, no compiled extension. Only importable on Windows.
"""

import ctypes
import functools
import os
import threading
import uuid
from ctypes import POINTER, byref, c_int, c_int64, c_long, c_ubyte, c_uint32, c_ulong, c_ushort, c_void_p, wintypes

import numpy as np

CAPTURE_RATE = 48000
CAPTURE_CHANNELS = 2

S_OK = 0
E_NOINTERFACE = -2147467262  # 0x80004002
VT_BLOB = 65
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
BUFFER_DURATION_HNS = 5_000_000  # 500 ms, in 100-ns units


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]


def make_guid(text):
    g = GUID()
    ctypes.memmove(byref(g), uuid.UUID(text).bytes_le, 16)
    return g


IID_IUnknown = make_guid("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = make_guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IActivateAudioInterfaceCompletionHandler = make_guid("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IAudioClient = make_guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = make_guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", c_int), ("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_int)]


class PROPVARIANT_BLOB(ctypes.Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("cbSize", c_ulong), ("pBlobData", c_void_p)]


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class WasapiError(RuntimeError):
    pass


def check(hr, what):
    if hr < 0:
        raise WasapiError(f"{what} failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")
    return hr


@functools.lru_cache(maxsize=None)
def _proto(restype, argtypes):
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)


def com_call(ptr, index, restype, argtypes, *args):
    """Call method number `index` of the COM interface at `ptr`."""
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    return _proto(restype, tuple(argtypes))(vtbl[index])(ptr, *args)


def com_release(ptr):
    if ptr and ptr.value:
        com_call(ptr, 2, c_ulong, ())


# --- the completion handler: a tiny COM object implemented in Python ------------------

_QI = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, POINTER(c_void_p))
_REF = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
_COMPLETED = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p)


class _HandlerVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI), ("AddRef", _REF), ("Release", _REF), ("ActivateCompleted", _COMPLETED)]


class _HandlerObject(ctypes.Structure):
    _fields_ = [("lpVtbl", POINTER(_HandlerVtbl))]


class CompletionHandler:
    _accepted = {bytes(IID_IUnknown), bytes(IID_IAgileObject), bytes(IID_IActivateAudioInterfaceCompletionHandler)}

    def __init__(self):
        self.done = threading.Event()
        # Keep every callback referenced on self, or ctypes frees them while Windows still calls them.
        self._vtbl = _HandlerVtbl(_QI(self._query), _REF(lambda this: 1), _REF(lambda this: 1),
                                  _COMPLETED(self._completed))
        self.obj = _HandlerObject(ctypes.pointer(self._vtbl))

    def _query(self, this, riid, ppv):
        if ctypes.string_at(riid, 16) in self._accepted:
            ppv[0] = ctypes.addressof(self.obj)
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def _completed(self, this, operation):
        self.done.set()
        return S_OK


# --- the source ---------------------------------------------------------------------

class ProcessLoopbackSource:
    label = "system"

    def __init__(self, buffer, pid, include_tree=True):
        """include_tree=True: record only pid's tree. False: record everything except pid's tree."""
        self.buffer = buffer
        self.pid = pid
        self.mode = (PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE if include_tree
                     else PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="process-loopback", daemon=True)
        self._thread.start()
        if not self._ready.wait(15):
            raise WasapiError("timed out starting process loopback capture")
        if self._error:
            raise self._error

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        ole32 = ctypes.WinDLL("ole32")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        client, capture, event = c_void_p(), c_void_p(), None
        try:
            client = self._activate()
            fmt = WAVEFORMATEX(1, CAPTURE_CHANNELS, CAPTURE_RATE, CAPTURE_RATE * 2 * CAPTURE_CHANNELS,
                               2 * CAPTURE_CHANNELS, 16, 0)
            flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                     | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM)
            check(com_call(client, 3, c_long, (c_int, wintypes.DWORD, c_int64, c_int64, POINTER(WAVEFORMATEX), c_void_p),
                           AUDCLNT_SHAREMODE_SHARED, flags, BUFFER_DURATION_HNS, 0, byref(fmt), None),
                  "IAudioClient::Initialize")
            event = kernel32.CreateEventW(None, False, False, None)
            check(com_call(client, 13, c_long, (wintypes.HANDLE,), event), "IAudioClient::SetEventHandle")
            check(com_call(client, 14, c_long, (POINTER(GUID), POINTER(c_void_p)),
                           byref(IID_IAudioCaptureClient), byref(capture)), "IAudioClient::GetService")
            check(com_call(client, 10, c_long, ()), "IAudioClient::Start")
        except Exception as exc:  # report to start(), which raises it in the main thread
            self._error = exc if isinstance(exc, WasapiError) else WasapiError(str(exc))
            self._ready.set()
            com_release(capture)
            com_release(client)
            ole32.CoUninitialize()
            return
        self._ready.set()
        try:
            while not self._stop.is_set():
                kernel32.WaitForSingleObject(event, 100)
                self._drain(capture)
        finally:
            com_call(client, 11, c_long, ())
            com_release(capture)
            com_release(client)
            kernel32.CloseHandle(event)
            ole32.CoUninitialize()

    def _activate(self):
        mmdevapi = ctypes.WinDLL("Mmdevapi")
        activate = mmdevapi.ActivateAudioInterfaceAsync
        activate.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT_BLOB), c_void_p, POINTER(c_void_p)]
        activate.restype = c_long
        params = AUDIOCLIENT_ACTIVATION_PARAMS(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, self.pid, self.mode)
        blob = PROPVARIANT_BLOB(vt=VT_BLOB, cbSize=ctypes.sizeof(params),
                                pBlobData=ctypes.cast(ctypes.pointer(params), c_void_p))
        handler = CompletionHandler()
        operation = c_void_p()
        check(activate(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(IID_IAudioClient), byref(blob),
                       ctypes.addressof(handler.obj), byref(operation)),
              "ActivateAudioInterfaceAsync (needs Windows 10 2004 or later)")
        try:
            if not handler.done.wait(10):
                raise WasapiError("audio interface activation never completed")
            result, client = c_long(), c_void_p()
            check(com_call(operation, 3, c_long, (POINTER(c_long), POINTER(c_void_p)), byref(result), byref(client)),
                  "GetActivateResult")
            check(result.value, "process loopback activation")
            return client
        finally:
            com_release(operation)

    def _drain(self, capture):
        while True:
            pending = c_uint32()
            check(com_call(capture, 5, c_long, (POINTER(c_uint32),), byref(pending)), "GetNextPacketSize")
            if pending.value == 0:
                return
            data, frames, flags = POINTER(c_ubyte)(), c_uint32(), wintypes.DWORD()
            check(com_call(capture, 3, c_long,
                           (POINTER(POINTER(c_ubyte)), POINTER(c_uint32), POINTER(wintypes.DWORD), c_void_p, c_void_p),
                           byref(data), byref(frames), byref(flags), None, None), "GetBuffer")
            n = frames.value
            if n:
                if flags.value & AUDCLNT_BUFFERFLAGS_SILENT:
                    mono = np.zeros(n, dtype=np.float32)
                else:
                    raw = ctypes.string_at(data, n * 2 * CAPTURE_CHANNELS)
                    mono = np.frombuffer(raw, dtype="<i2").reshape(-1, CAPTURE_CHANNELS).mean(axis=1) / 32768.0
                self.buffer.write(mono)
            com_call(capture, 4, c_long, (c_uint32,), n)


def own_pid():
    return os.getpid()
