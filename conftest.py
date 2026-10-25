"""Stub Windows COM modules so the test-suite runs on any OS."""

import sys
import types

# ----------------------------------------------------------------------------
# Stub win32com / pythoncom before importing the package
# ----------------------------------------------------------------------------

try:
    import win32com.client  # noqa: F401
    import pythoncom  # noqa: F401
except ImportError:
    pythoncom = types.ModuleType("pythoncom")
    for i, n in enumerate(["VT_EMPTY", "VT_NULL", "VT_I2", "VT_I4", "VT_R4", "VT_R8"]):
        setattr(pythoncom, n, i)
    pythoncom.VT_BSTR, pythoncom.VT_DISPATCH, pythoncom.VT_BOOL = 8, 9, 11
    pythoncom.VT_ARRAY, pythoncom.VT_BYREF = 0x2000, 0x4000
    pythoncom.Nothing, pythoncom.Empty, pythoncom.Missing = None, None, None
    pythoncom.CoInitialize = lambda: None

    class VARIANT:
        def __init__(self, vt, value):
            self.varianttype, self.value = vt, value

        def __repr__(self):
            return f"VARIANT({self.varianttype}, {self.value!r})"

    client = types.ModuleType("win32com.client")
    client.VARIANT = VARIANT
    client.Dispatch = client.GetObject = client.GetActiveObject = lambda *a, **k: None
    client.dynamic = types.SimpleNamespace(Dispatch=lambda *a, **k: None)
    win32com = types.ModuleType("win32com")
    win32com.client = client
    sys.modules.update({"win32com": win32com, "win32com.client": client, "pythoncom": pythoncom})

