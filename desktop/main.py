"""
Folder Search (desktop) - pywebview wrapper around ../폴더검색.html, the
same file the web version uses. The page detects at runtime whether it is
running inside pywebview or a plain browser and switches its backend
(DesktopBackend vs WebBackend) accordingly - see 폴더검색.html.

Uses the OS's native folder picker and reads files directly via Python's
filesystem APIs, so there is no "this folder is blocked" restriction like
the browser's File System Access API has for Documents/Desktop/Downloads.
"""
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
import webview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
CACHE_DIR = os.path.join(APP_DIR, "cache")
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_HISTORY = 8
SCAN_CHUNK = 200


def cache_file_for(path):
    h = hashlib.md5(path.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".json")


def load_scan_cache(path):
    """
    Returns (meta, chunk_json_strings) or None. Each entry in
    chunk_json_strings is already a ready-to-send JSON array - the file is
    stored pre-chunked (one metadata line, then one already-serialized
    chunk per line) specifically so loading from cache never needs to
    json.loads() the (possibly 100MB+) document data and then json.dumps()
    it straight back out again just to hand it to evaluate_js. That
    parse-then-reserialize round trip was, once measured, over half the
    cost of a "cached" load.
    """
    cf = cache_file_for(path)
    if not os.path.exists(cf):
        return None
    try:
        with open(cf, "r", encoding="utf-8") as f:
            meta = json.loads(f.readline())
            chunk_lines = [line.rstrip("\n") for line in f if line.strip()]
        return meta, chunk_lines
    except (OSError, ValueError):
        return None


def save_scan_cache(path, allowed_exts, exclude_names, total, chunk_json_strings):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        meta = {"exts": allowed_exts, "excludes": exclude_names, "total": total}
        with open(cache_file_for(path), "w", encoding="utf-8") as f:
            f.write(json.dumps(meta) + "\n")
            for s in chunk_json_strings:
                f.write(s + "\n")
    except OSError:
        pass


def delete_scan_cache(path):
    try:
        cf = cache_file_for(path)
        if os.path.exists(cf):
            os.remove(cf)
    except OSError:
        pass


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def read_text(path):
    """Try a couple of common encodings; return '' if the file can't be
    read as text at all (still gets indexed by filename)."""
    for enc in ("utf-8", "cp949", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return ""


class Api:
    def __init__(self):
        # leading underscore matters: pywebview's inject_pywebview() reflects
        # over every non-underscore attribute of this object via dir() to
        # build the exposed JS API, and would otherwise recurse into the
        # live Window's native WebView2/winforms internals and blow the
        # stack (this is what was causing the slow-close bug).
        self._window = None

    def _add_history(self, path):
        name = os.path.basename(path.rstrip("\\/")) or path
        history = [h for h in load_history() if h.get("path") != path]
        history.insert(0, {"path": path, "name": name})
        # anything pushed out of the remembered list no longer needs its
        # scan cache kept around either
        for dropped in history[MAX_HISTORY:]:
            delete_scan_cache(dropped["path"])
        history = history[:MAX_HISTORY]
        save_history(history)
        return history

    def get_history(self):
        return load_history()

    def remove_history(self, path):
        history = [h for h in load_history() if h.get("path") != path]
        save_history(history)
        delete_scan_cache(path)
        return history

    def pick_folder(self):
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not path:
            return None
        history = self._add_history(path)
        return {"path": path, "name": os.path.basename(path.rstrip("\\/")) or path, "history": history}

    def use_history_entry(self, path):
        if not os.path.isdir(path):
            return None
        history = self._add_history(path)
        return {"path": path, "name": os.path.basename(path.rstrip("\\/")) or path, "history": history}

    def open_file(self, path):
        try:
            os.startfile(path)  # Windows: launch with the OS default app
            return True
        except OSError:
            return False

    def scan_folder(self, root_path, allowed_exts, exclude_names, force_refresh=False):
        """
        allowed_exts: list[str] lowercase, no dot, or None/[] for "allow all"
        exclude_names: list[str] of directory names to skip anywhere in the tree
        force_refresh: True (the page's "새로고침" button) skips the on-disk
            cache below and always re-reads from the filesystem.

        Unless force_refresh, first checks a per-folder cache file on disk
        (data/cache/<md5 of path>.json) saved from a previous run, so
        closing and reopening the app doesn't mean reading everything from
        disk again - the page already has its own in-memory cache for
        switching folders within one running session, but that memory is
        gone once the app restarts. The disk cache is a straight dict
        match on the current ext/exclude filters; it's discarded whenever
        that folder is dropped from history or "새로고침" is pressed.

        Streams both progress AND the actual document data to the page in
        chunks via a single window.evaluate_js call per chunk
        (window.onScanChunk(chunk, done, total)), instead of building the
        whole list in memory and marshalling it across the JS bridge in one
        huge call at the end - for a folder with thousands of files that
        final one-shot transfer is what caused the visible pause between
        "done reading" and "search actually works". Two more things that
        turned out to matter once measured against a real 8000+ file
        folder: reading files with a thread pool (I/O-bound, so Python's
        GIL isn't in the way) cut the read time by ~40%, and each
        evaluate_js call has enough fixed overhead that halving the call
        count (one merged call instead of two) and using bigger chunks
        (fewer, larger calls) both measurably helped.
        The return value is just a completion count; the page already has
        everything it needs by the time this returns.
        """
        if not force_refresh:
            cached = load_scan_cache(root_path)
            cache_note = "no cache file"
            if cached:
                meta, chunk_lines = cached
                if meta.get("exts") == allowed_exts and meta.get("excludes") == exclude_names:
                    total = meta.get("total", 0)
                    done = 0
                    for chunk_json in chunk_lines:
                        done = min(done + SCAN_CHUNK, total)
                        try:
                            self._window.evaluate_js(
                                f"window.onScanChunk({chunk_json}, {done}, {total})"
                            )
                        except Exception:
                            pass
                    try:
                        self._window.evaluate_js("window.onScanSource('cache')")
                    except Exception:
                        pass
                    return total
                cache_note = f"filter mismatch: cached={meta.get('exts')!r}/{meta.get('excludes')!r} vs requested={allowed_exts!r}/{exclude_names!r}"
            try:
                self._window.evaluate_js(f"window.onScanSource('live', {json.dumps(cache_note)})")
            except Exception:
                pass
        else:
            try:
                self._window.evaluate_js("window.onScanSource('live', '새로고침으로 강제 재스캔')")
            except Exception:
                pass

        exclude_set = set(exclude_names or [])
        ext_set = set(e.lower() for e in allowed_exts) if allowed_exts else None

        # first pass: collect matching file paths (cheap, no content read yet)
        candidates = []

        def onerror(_exc):
            pass  # permission-denied etc: just skip that subtree, keep going

        for dirpath, dirnames, filenames in os.walk(root_path, onerror=onerror):
            dirnames[:] = [d for d in dirnames if d not in exclude_set]
            for fname in filenames:
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                if ext_set is not None and ext not in ext_set:
                    continue
                candidates.append((os.path.join(dirpath, fname), fname, ext))

        total = len(candidates)

        def read_one(item):
            full_path, fname, ext = item
            try:
                st = os.stat(full_path)
                content = read_text(full_path) if st.st_size <= MAX_FILE_BYTES else ""
                rel_path = os.path.relpath(full_path, root_path).replace("\\", "/")
                return {
                    "path": rel_path,
                    "fullPath": full_path,
                    "name": fname,
                    "ext": ext,
                    "mtime": int(st.st_mtime * 1000),
                    "size": st.st_size,
                    "content": content,
                }
            except OSError:
                return None

        chunk = []
        chunk_json_strings = []
        done = 0
        with ThreadPoolExecutor(max_workers=16) as pool:
            for doc in pool.map(read_one, candidates):
                done += 1
                if doc is not None:
                    chunk.append(doc)
                if done % SCAN_CHUNK == 0 or done == total:
                    chunk_json = json.dumps(chunk)
                    try:
                        self._window.evaluate_js(
                            f"window.onScanChunk({chunk_json}, {done}, {total})"
                        )
                    except Exception:
                        pass
                    chunk_json_strings.append(chunk_json)
                    chunk = []

        save_scan_cache(root_path, allowed_exts, exclude_names, total, chunk_json_strings)
        return total


def main():
    api = Api()
    # shared with the web version - one file works as both, see 폴더검색.html's
    # environment detection (pywebview vs plain browser)
    index_path = os.path.join(APP_DIR, "..", "폴더검색.html")
    window = webview.create_window(
        "폴더검색",
        index_path,
        js_api=api,
        width=1100,
        height=780,
        min_size=(700, 480),
    )
    api._window = window
    webview.start()
    # webview.start() already blocks until the window is closed, so once it
    # returns there is nothing left to wait for - exit immediately rather
    # than waiting on any leftover .NET/WebView2 teardown.
    os._exit(0)


if __name__ == "__main__":
    main()
