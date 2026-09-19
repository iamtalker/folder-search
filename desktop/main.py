"""
Folder Search (desktop) - pywebview wrapper around index.html.

Uses the OS's native folder picker and reads files directly via Python's
filesystem APIs, so there is no "this folder is blocked" restriction like
the browser's File System Access API has for Documents/Desktop/Downloads.
"""
import json
import os
import sys
import webview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_HISTORY = 8


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
        self.window = None

    def _add_history(self, path):
        name = os.path.basename(path.rstrip("\\/")) or path
        history = [h for h in load_history() if h.get("path") != path]
        history.insert(0, {"path": path, "name": name})
        history = history[:MAX_HISTORY]
        save_history(history)
        return history

    def get_history(self):
        return load_history()

    def remove_history(self, path):
        history = [h for h in load_history() if h.get("path") != path]
        save_history(history)
        return history

    def pick_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
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

    def scan_folder(self, root_path, allowed_exts, exclude_names):
        """
        allowed_exts: list[str] lowercase, no dot, or None/[] for "allow all"
        exclude_names: list[str] of directory names to skip anywhere in the tree
        Streams progress to the page via window.evaluate_js, then returns the
        full document list at the end.
        """
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
        docs = []
        for i, (full_path, fname, ext) in enumerate(candidates):
            try:
                st = os.stat(full_path)
                content = read_text(full_path) if st.st_size <= MAX_FILE_BYTES else ""
                rel_path = os.path.relpath(full_path, root_path).replace("\\", "/")
                docs.append({
                    "path": rel_path,
                    "fullPath": full_path,
                    "name": fname,
                    "ext": ext,
                    "mtime": int(st.st_mtime * 1000),
                    "size": st.st_size,
                    "content": content,
                })
            except OSError:
                pass

            if i % 40 == 0 or i == total - 1:
                try:
                    self.window.evaluate_js(f"window.onScanProgress({i + 1}, {total})")
                except Exception:
                    pass

        return docs


def main():
    api = Api()
    index_path = os.path.join(APP_DIR, "index.html")
    window = webview.create_window(
        "폴더검색",
        index_path,
        js_api=api,
        width=1100,
        height=780,
        min_size=(700, 480),
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
