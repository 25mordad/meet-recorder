"""Windows-only checks of the process-loopback code. Skipped on other systems."""

import ctypes
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_struct_layouts_match_windows_headers():
    from meetrec.sources import win_process_loopback as w
    assert ctypes.sizeof(w.GUID) == 16
    assert ctypes.sizeof(w.WAVEFORMATEX) == 18
    assert ctypes.sizeof(w.AUDIOCLIENT_ACTIVATION_PARAMS) == 12
    assert ctypes.sizeof(w.PROPVARIANT_BLOB) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)


def test_process_loopback_starts_and_stops():
    """Activates a real capture of all system audio (except this process) for one second."""
    from meetrec.buffer import SampleBuffer
    from meetrec.sources.win_process_loopback import ProcessLoopbackSource, own_pid
    buf = SampleBuffer()
    src = ProcessLoopbackSource(buf, own_pid(), include_tree=False)
    src.start()
    time.sleep(1.0)
    src.stop()
    # Windows may send no packets while nothing plays, so only check that nothing crashed
    # and that whatever arrived is sane.
    assert buf.available() <= 48000 * 2
