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
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import webview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, "frozen", False))


def resource_path(relative_path):
    """
    Locate 폴더검색.html whether running as a plain script or as the packaged
    exe. Deliberately kept as a plain external file next to the exe rather
    than embedded inside it (PyInstaller can bundle it in and extract it to
    a hidden temp folder at each run, but that makes it invisible - the exe
    and the html file are meant to be two files sitting together, the same
    as running from source, just without needing Python installed).
    """
    base = os.path.dirname(sys.executable) if FROZEN else os.path.join(APP_DIR, "..")
    return os.path.join(base, relative_path)


def app_data_dir():
    """
    Where history.json/cache/ live. Unfrozen, that's next to this script,
    same as always. Frozen, APP_DIR would resolve inside the --onefile
    build's temp extraction folder (sys._MEIPASS-adjacent), which is wiped
    after every run - anything written there wouldn't survive to the next
    launch, defeating both the history list and the whole point of the
    on-disk scan cache. %LOCALAPPDATA% is the standard, always-writable
    place for a Windows app to keep its own data regardless of where the
    exe itself was downloaded to.
    """
    if not FROZEN:
        return APP_DIR
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "FolderSearch")
    os.makedirs(d, exist_ok=True)
    return d


DATA_DIR = app_data_dir()
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_HISTORY = 8
SCAN_CHUNK = 200
MAX_RESULTS_SHOWN = 200


# =============================================================================
# Boolean query parser / scorer / snippet extraction - a straight Python port
# of the same logic in 폴더검색.html (tokenize/parseQuery/evalNode/
# collectPositiveWords/score/snippetAround). Ported here, rather than shared,
# because of *why* search moved server-side at all: sending every file's full
# content to the JS side (so it could search client-side, like the web
# version still does) meant marshalling ~200MB+ across the Python<->WebView2
# bridge on every scan of a large folder, which measured out to several
# extra seconds versus the web version - which has no such bridge at all.
# Searching here instead means only small result pages (with a short
# snippet, not full content) ever cross that bridge.
# =============================================================================

_TOKEN_RE = re.compile(r'"([^"]*)"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|\S+')


def tokenize_query(q):
    """
    depth tracks how many '(' are still unclosed. A plain \\S+ match is
    greedy and doesn't stop at ')', so "(NOT word)" without a space before
    the ')' would otherwise swallow it into the word ("word)") and leave the
    group unclosed. When depth > 0, peel a trailing run of ')' off such a
    word (up to depth many) into their own tokens instead - ')' is never a
    meaningful character inside an unquoted search word once a group is
    open, so this can't misinterpret an intentional literal word.
    """
    tokens = []
    depth = 0
    for m in _TOKEN_RE.finditer(q):
        t = m.group(0)
        if t == "(":
            tokens.append({"type": "("})
            depth += 1
        elif t == ")":
            tokens.append({"type": ")"})
            depth = max(0, depth - 1)
        elif t in ("AND", "OR", "NOT"):
            tokens.append({"type": t})
        elif m.group(1) is not None:
            tokens.append({"type": "WORD", "value": m.group(1)})
        else:
            stripped = t.rstrip(")")
            trailing_close = min(depth, len(t) - len(stripped))
            if trailing_close:
                core = t[:len(t) - trailing_close]
                if core:
                    tokens.append({"type": "WORD", "value": core})
                for _ in range(trailing_close):
                    tokens.append({"type": ")"})
                depth -= trailing_close
            else:
                tokens.append({"type": "WORD", "value": t})
    return tokens


def parse_query(q):
    tokens = tokenize_query(q)
    if not tokens:
        return None
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def nxt():
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_or():
        node = parse_and()
        while peek() and peek()["type"] == "OR":
            nxt()
            node = {"op": "OR", "left": node, "right": parse_and()}
        return node

    def parse_and():
        node = parse_factor()
        while peek() and peek()["type"] in ("AND", "NOT", "WORD", "("):
            op = "AND"
            if peek()["type"] in ("AND", "NOT"):
                op = nxt()["type"]
            right = parse_factor()
            if right is None:
                break
            node = {"op": op, "left": node, "right": right}
        return node

    def parse_factor():
        t = peek()
        if t is None:
            return None
        if t["type"] == "(":
            nxt()
            node = parse_or()
            if peek() and peek()["type"] == ")":
                nxt()
            return node
        if t["type"] == "WORD":
            nxt()
            return {"op": "WORD", "value": t["value"].lower()}
        return None

    return parse_or()


def eval_node(node, haystack):
    if node is None:
        return True
    op = node["op"]
    if op == "WORD":
        return node["value"] in haystack
    if op == "AND":
        return eval_node(node["left"], haystack) and eval_node(node["right"], haystack)
    if op == "OR":
        return eval_node(node["left"], haystack) or eval_node(node["right"], haystack)
    if op == "NOT":
        return eval_node(node["left"], haystack) and not eval_node(node["right"], haystack)
    return True


def collect_positive_words(node, out):
    if node is None:
        return
    if node["op"] == "WORD":
        out.append(node["value"])
        return
    if node["op"] == "NOT":
        collect_positive_words(node["left"], out)  # skip the excluded side
        return
    collect_positive_words(node["left"], out)
    collect_positive_words(node["right"], out)


def count_occurrences(haystack, needle):
    if not needle:
        return 0
    count = 0
    idx = 0
    while True:
        idx = haystack.find(needle, idx)
        if idx == -1:
            return count
        count += 1
        idx += len(needle)


def score_doc(doc, positive_words, raw_query):
    haystack = doc["_haystack"]
    s = sum(count_occurrences(haystack, w) for w in positive_words)
    lname = doc["name"].lower()
    q = raw_query.strip().lower()
    if q and (lname == q or lname == q + "." + doc["ext"]):
        s += 1000
    elif q and q in lname:
        s += 50
    return s


def snippet_around(content, words, radius):
    if not content:
        return ""
    lower = content.lower()
    idx = -1
    for w in words:
        idx = lower.find(w)
        if idx != -1:
            break
    if idx == -1:
        return content[:radius * 2]
    start = max(0, idx - radius)
    end = min(len(content), idx + radius)
    return ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")


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
        self._docs = []        # currently-loaded folder's documents (kept
                                # server-side; see search())
        self._docs_root = None  # which folder self._docs belongs to

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
        force_refresh: True (the page's "새로고침" button) ignores the on-disk
            cache below entirely and re-reads every file's content, even if
            unchanged.

        Unless force_refresh, first loads a per-folder cache file on disk
        (desktop/cache/<md5 of path>.json) saved from a previous run - but
        the cache is no longer trusted blindly. The folder is always walked
        to get the current file list, and each candidate file is stat'd
        (cheap) and compared against the cached entry's mtime/size: unchanged
        files reuse their cached content as-is (no re-read), while new or
        changed files are read fresh. Files present in the cache but no
        longer on disk are simply dropped by virtue of not being in the
        fresh candidate list. This keeps closing/reopening the app fast
        without ever serving stale content when files were edited outside
        the "새로고침" button.

        Reads (or reuses from cache) the full document set, including file
        content, and keeps it server-side in self._docs - it does NOT send
        that content to the page. Search runs here too (see search()) for
        exactly that reason: earlier versions streamed every file's content
        to the page so it could search client-side like the web version
        does, but marshalling that much data (~200MB+ for a large folder)
        across the Python<->WebView2 bridge measured out to several extra
        seconds versus the web version, which has no such bridge. Only
        window.onScanProgress(done, total) - two small numbers - crosses
        the bridge during a scan now; search results (small, paginated,
        with a short snippet rather than full content) are the only other
        thing that does.
        The return value is just the total file count.
        """
        cached_by_path = {}
        cache_note = None
        if not force_refresh:
            cached = load_scan_cache(root_path)
            if cached:
                meta, chunk_lines = cached
                if meta.get("exts") == allowed_exts and meta.get("excludes") == exclude_names:
                    for chunk_json in chunk_lines:
                        for d in json.loads(chunk_json):
                            cached_by_path[d["fullPath"]] = d
                else:
                    cache_note = f"filter mismatch: cached={meta.get('exts')!r}/{meta.get('excludes')!r} vs requested={allowed_exts!r}/{exclude_names!r}"
            else:
                cache_note = "no cache file"
        else:
            cache_note = "새로고침으로 강제 재스캔"

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
        reused_count = [0]

        def read_one(item):
            full_path, fname, ext = item
            try:
                st = os.stat(full_path)
                mtime_ms = int(st.st_mtime * 1000)
                cached_doc = cached_by_path.get(full_path)
                if (
                    cached_doc is not None
                    and cached_doc.get("mtime") == mtime_ms
                    and cached_doc.get("size") == st.st_size
                ):
                    reused_count[0] += 1
                    return cached_doc
                content = read_text(full_path) if st.st_size <= MAX_FILE_BYTES else ""
                rel_path = os.path.relpath(full_path, root_path).replace("\\", "/")
                return {
                    "path": rel_path,
                    "fullPath": full_path,
                    "name": fname,
                    "ext": ext,
                    "mtime": mtime_ms,
                    "size": st.st_size,
                    "content": content,
                }
            except OSError:
                return None

        all_docs = []
        chunk_json_strings = []
        chunk = []
        done = 0
        with ThreadPoolExecutor(max_workers=16) as pool:
            for doc in pool.map(read_one, candidates):
                done += 1
                if doc is not None:
                    all_docs.append(doc)
                    chunk.append(doc)
                if done % SCAN_CHUNK == 0 or done == total:
                    chunk_json_strings.append(json.dumps(chunk))
                    try:
                        self._window.evaluate_js(f"window.onScanProgress({done}, {total})")
                    except Exception:
                        pass
                    chunk = []

        if cache_note is None:
            stale = total - reused_count[0]
            cache_note = "no changes" if stale == 0 else f"{stale}/{total} files re-read (new/changed)"
        try:
            source = "cache" if reused_count[0] == total and total > 0 else "live"
            self._window.evaluate_js(f"window.onScanSource({json.dumps(source)}, {json.dumps(cache_note)})")
        except Exception:
            pass

        self._index_docs(root_path, all_docs)
        save_scan_cache(root_path, allowed_exts, exclude_names, total, chunk_json_strings)
        return total

    def _index_docs(self, root_path, docs):
        for d in docs:
            d["_haystack"] = (d["name"] + "\n" + d["content"]).lower()
        self._docs = docs
        self._docs_root = root_path

    def search(self, root_path, query, sort_mode, date_from=None, date_to=None,
               sort_asc=False, page=1, page_size=MAX_RESULTS_SHOWN):
        """
        Runs entirely server-side against self._docs (populated by
        scan_folder) and returns only a small page of results - see
        scan_folder's docstring for why. Mirrors 폴더검색.html's WebBackend
        search logic (tokenize/parseQuery/evalNode/score/snippet) exactly,
        just in Python instead of JS.

        date_from/date_to: optional epoch-ms bounds (inclusive) on a doc's
        mtime, from the page's date-range inputs.
        sort_asc: reverses the default order (lowest score / oldest first).
        page/page_size: 1-indexed pagination over the matched set.
        """
        if root_path != self._docs_root:
            return {"total": 0, "matchedTotal": 0, "results": []}

        page_size = max(1, min(int(page_size or MAX_RESULTS_SHOWN), 2000))
        page = max(1, int(page or 1))

        q = (query or "").strip()
        node = parse_query(q) if q else None
        positive_words = []
        if node:
            collect_positive_words(node, positive_words)

        matched = [
            d for d in self._docs
            if (date_from is None or d["mtime"] >= date_from)
            and (date_to is None or d["mtime"] <= date_to)
            and (node is None or eval_node(node, d["_haystack"]))
        ]

        scores = None
        if sort_mode == "relevance" and q:
            scores = {id(d): score_doc(d, positive_words, q) for d in matched}
            matched.sort(key=lambda d: scores[id(d)], reverse=not sort_asc)
        else:
            matched.sort(key=lambda d: d["mtime"], reverse=not sort_asc)

        matched_total = len(matched)
        start = (page - 1) * page_size
        results = []
        for d in matched[start:start + page_size]:
            results.append({
                "path": d["path"],
                "fullPath": d["fullPath"],
                "name": d["name"],
                "ext": d["ext"],
                "mtime": d["mtime"],
                "size": d["size"],
                "score": scores[id(d)] if scores else None,
                "snippet": snippet_around(d["content"], positive_words, 120),
                "matchedWords": positive_words,
            })
        return {"total": len(self._docs), "matchedTotal": matched_total, "results": results}

    def get_file_content(self, root_path, path):
        if root_path != self._docs_root:
            return None
        for d in self._docs:
            if d["path"] == path:
                return d["content"]
        return None


def main():
    api = Api()
    # shared with the web version - one file works as both, see 폴더검색.html's
    # environment detection (pywebview vs plain browser)
    index_path = resource_path("폴더검색.html")
    if not os.path.exists(index_path):
        # Reuse webview itself for this message (proven to work in the
        # frozen build) rather than a raw ctypes MessageBoxW call, which
        # turned out not to reliably show up from a --windowed PyInstaller
        # build.
        err_html = (
            "<html><body style='font-family:sans-serif;padding:24px;line-height:1.6'>"
            "<h2>폴더검색.html 파일을 찾을 수 없습니다</h2>"
            f"<p>이 exe와 같은 폴더에 <b>폴더검색.html</b>이 있어야 합니다:</p>"
            f"<p><code>{os.path.dirname(index_path)}</code></p>"
            "</body></html>"
        )
        webview.create_window("폴더검색 - 파일 없음", html=err_html, width=520, height=220)
        webview.start()
        return
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
