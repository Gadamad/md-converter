"""
Native macOS drag-and-drop handler for pywebview.
Swizzles WebKitHost's performDragOperation: so files and browser links
get routed to the saved queue instead of navigating the webview.
"""

import ctypes
import ctypes.util
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSFilenamesPboardType,
    NSPasteboardTypeFileURL,
    NSPasteboardTypeString,
    NSPasteboardTypeURL,
)
from Foundation import NSURL

# Load objc runtime for low-level method swizzling
_libobjc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

_libobjc.class_getInstanceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_libobjc.class_getInstanceMethod.restype = ctypes.c_void_p

_libobjc.method_getImplementation.argtypes = [ctypes.c_void_p]
_libobjc.method_getImplementation.restype = ctypes.c_void_p

_libobjc.method_setImplementation.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_libobjc.method_setImplementation.restype = ctypes.c_void_p

_libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
_libobjc.sel_registerName.restype = ctypes.c_void_p

_libobjc.object_getClass.argtypes = [ctypes.c_void_p]
_libobjc.object_getClass.restype = ctypes.c_void_p

# Shared state
_drop_callback = None
_link_callback = None
_orig_perform_imp = None


def _extract_paths(pboard):
    """Extract file paths from a drag pasteboard."""
    legacy = pboard.propertyListForType_(NSFilenamesPboardType)
    if legacy:
        return [str(p) for p in legacy]
    paths = []
    items = pboard.pasteboardItems()
    if items:
        for item in items:
            url_str = item.stringForType_(NSPasteboardTypeFileURL)
            if url_str:
                url = NSURL.URLWithString_(url_str)
                if url and url.isFileURL() and url.path():
                    paths.append(str(url.path()))
    return paths


def _extract_links(pboard):
    """Prefer browser URL data to display-title text on the same pasteboard."""
    items = pboard.pasteboardItems() or []
    urls = [str(value) for item in items if (value := item.stringForType_(NSPasteboardTypeURL))]
    if not urls:
        value = pboard.stringForType_(NSPasteboardTypeURL)
        if value:
            urls = [str(value)]
    if urls:
        return {"urls": list(dict.fromkeys(urls))}
    texts = [str(value) for item in items if (value := item.stringForType_(NSPasteboardTypeString))]
    if not texts:
        value = pboard.stringForType_(NSPasteboardTypeString)
        if value:
            texts = [str(value)]
    text = "\n".join(texts)
    return {"text": text} if text.strip() else None


def _dispatch_drop(pboard, file_callback, link_callback):
    """Consume recognized drops before WebKit gets a chance to navigate."""
    paths = _extract_paths(pboard)
    if paths and file_callback:
        threading.Thread(target=file_callback, args=(paths,), daemon=True).start()
        return True
    payload = _extract_links(pboard) if link_callback else None
    if payload:
        threading.Thread(target=link_callback, args=(payload,), daemon=True).start()
        return True
    return False


def setup_native_drop(webview_window, callback, delay=2.0, link_callback=None):
    """
    Swizzle WebKitHost's performDragOperation: using ctypes
    to get real file paths from Finder and website URLs from browser drops.
    The optional link callback accepts {"urls": [...]} or {"text": "..."}.
    """
    global _drop_callback, _link_callback, _orig_perform_imp
    _drop_callback = callback
    _link_callback = link_callback

    time.sleep(delay)

    try:
        app = NSApplication.sharedApplication()

        target_view = None
        for ns_window in app.windows():
            cv = ns_window.contentView()
            if cv and "WebKitHost" in cv.className():
                target_view = cv
                break

        if target_view is None:
            print("[native_drop] WebKitHost not found")
            return False

        if link_callback:
            registered = list(target_view.registeredDraggedTypes() or [])
            types = list(dict.fromkeys(registered + [NSFilenamesPboardType, NSPasteboardTypeFileURL,
                                                   NSPasteboardTypeURL, NSPasteboardTypeString]))
            target_view.performSelectorOnMainThread_withObject_waitUntilDone_(
                "registerForDraggedTypes:", types, False)

        # Get the raw ObjC class pointer via ctypes
        view_ptr = objc.pyobjc_id(target_view)
        cls_ptr = _libobjc.object_getClass(view_ptr)

        # Get the existing performDragOperation: method
        sel = _libobjc.sel_registerName(b"performDragOperation:")
        method = _libobjc.class_getInstanceMethod(cls_ptr, sel)
        if not method:
            print("[native_drop] performDragOperation: not found")
            return False

        # Save original implementation
        _orig_perform_imp = _libobjc.method_getImplementation(method)

        # Define replacement: BOOL performDragOperation:(id sender)
        # C signature: BOOL(id self, SEL _cmd, id sender)
        PERFORM_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_bool,      # return BOOL
            ctypes.c_void_p,    # self
            ctypes.c_void_p,    # _cmd
            ctypes.c_void_p,    # sender (id<NSDraggingInfo>)
        )

        def replacement_perform(self_ptr, cmd_ptr, sender_ptr):
            """Our replacement for performDragOperation:."""
            try:
                # Convert sender pointer back to Python ObjC object
                sender = objc.objc_object(c_void_p=sender_ptr)
                pboard = sender.draggingPasteboard()
                if _dispatch_drop(pboard, _drop_callback, _link_callback):
                    return True
            except Exception as e:
                print(f"[native_drop] drop handler error: {e}")

            # Fall back to original
            if _orig_perform_imp:
                orig_func = PERFORM_TYPE(_orig_perform_imp)
                return orig_func(self_ptr, cmd_ptr, sender_ptr)
            return False

        # Must keep a reference so it's not garbage collected
        global _replacement_ref
        _replacement_ref = PERFORM_TYPE(replacement_perform)

        # Swap the implementation
        _libobjc.method_setImplementation(method, _replacement_ref)

        return True

    except Exception as e:
        print(f"[native_drop] setup failed: {e}")
        return False
