# 폴더검색 (Folder Search)

브라우저에서 로컬 폴더를 골라 그 안의 파일들을 (이름 + 내용까지) 검색하는 단일 HTML 파일 도구입니다.
서버나 설치 없이, 이 저장소의 `폴더검색.html` 파일 하나만 다운로드해서 브라우저로 열면 바로 씁니다.

A single self-contained HTML file that lets you pick a local folder in your browser and full-text search its files — no server, no install. Just download `폴더검색.html` and open it in your browser.

세 가지 형태가 있습니다: **웹 버전**(`폴더검색.html` 하나) / **데스크톱 exe**(`FolderSearch.exe` + `폴더검색.html`, 같은 폴더에 두고 실행 — 파이썬 설치 불필요, [Releases](../../releases)에서 다운로드) / **데스크톱 파이썬 버전**(`desktop/` 폴더, 직접 실행/개발용).

There are three forms: a **web version** (single file `폴더검색.html`), a **standalone desktop exe** (`FolderSearch.exe` + `폴더검색.html`, kept together in the same folder — no Python install needed, download from [Releases](../../releases)), and the **desktop Python source** (`desktop/` folder, for running from source / development).

## 요구사항 / Requirements

- **웹 버전**: Chrome 또는 Edge (File System Access API를 사용합니다. Firefox/Safari는 아직 미지원)
- **Web version**: Chrome or Edge (uses the File System Access API; not yet supported in Firefox/Safari)
- **데스크톱 exe**: Windows + WebView2 런타임(보통 이미 있음). 그 외 아무것도 설치할 필요 없음(단, `FolderSearch.exe`와 `폴더검색.html`이 같은 폴더에 있어야 함).
- **Desktop exe**: Windows + the WebView2 runtime (usually already present). Nothing else to install (but `FolderSearch.exe` and `폴더검색.html` must be in the same folder).
- **데스크톱 파이썬 버전**: Python 3 + `pip install -r desktop/requirements.txt` (Windows, WebView2 런타임 필요)
- **Desktop Python version**: Python 3 + `pip install -r desktop/requirements.txt` (Windows, needs the WebView2 runtime)

## 기능 / Features

- 📁 폴더 선택 후 하위 폴더까지 재귀적으로 스캔
- 검색어와 파일명/본문 일치 정도로 **관련도순** 정렬, **최신순** 정렬도 지원
- `AND` / `OR` / `NOT` + 괄호를 쓰는 불리언 검색 (`"정확한 구절"` 검색도 가능)
- 🔄 새로고침 버튼으로 폴더를 다시 읽어 최신 상태 반영
- 최근 사용한 폴더 여러 개를 기억해뒀다가 클릭 한 번으로 전환 (브라우저의 IndexedDB에 저장, 서버로 전송되는 데이터 없음)
- 권한 없는 시스템 폴더(`System Volume Information` 등)는 자동으로 건너뜀
- 대상 확장자 / 제외 폴더 이름을 직접 편집 가능

## 사용법 / Usage

**웹 버전**: `폴더검색.html`을 다운로드해서 더블클릭으로 엽니다 (Chrome/Edge).
**Web version**: download `폴더검색.html` and open it (Chrome/Edge).

**데스크톱 exe**: [Releases](../../releases)에서 `FolderSearch.exe`와 `폴더검색.html`을 둘 다 다운로드해서 같은 폴더에 넣고 `FolderSearch.exe`를 실행합니다.
**Desktop exe**: download both `FolderSearch.exe` and `폴더검색.html` from [Releases](../../releases), keep them in the same folder, and run `FolderSearch.exe`.

**데스크톱 파이썬 버전(소스로 실행)**: 저장소 전체(`폴더검색.html` + `desktop/`)를 받아서 `pip install -r desktop/requirements.txt` 후 루트의 `run.bat` 실행 (또는 `python desktop/main.py`).
**Desktop Python version (run from source)**: grab the whole repo (`폴더검색.html` + `desktop/`), `pip install -r desktop/requirements.txt`, then run `run.bat` at the repo root (or `python desktop/main.py`).

1. "📁 폴더 선택"을 눌러 검색할 폴더를 고릅니다.
2. 검색창에 검색어를 입력합니다. 공백은 AND로 동작하고, `OR`/`NOT`과 괄호도 쓸 수 있습니다.
3. 폴더 내용이 바뀌었다면 "🔄 새로고침"을 눌러 다시 읽습니다.

### 웹 버전 vs 데스크톱 버전 / Web vs Desktop

**데스크톱 버전을 만든 이유가 바로 이겁니다**: 웹 버전은 브라우저(File System Access API) 보안 정책상 "문서/바탕화면/다운로드" 같은 몇몇 폴더를 아예 선택하지 못하게 막혀있습니다. 데스크톱 버전은 OS의 파일 선택창을 그대로 쓰기 때문에 이 제한이 없어서, 막혀있는 폴더까지 검색하고 싶을 때 씁니다.

**This is exactly why the desktop version exists**: the web version's browser API (File System Access API) refuses to let you pick certain folders at all — Documents, Desktop, Downloads. The desktop version uses the OS's native folder picker instead, which has no such restriction, so it's the one to use when you need to search a folder the web version won't even let you open.

## 왜 만들었나 / Why

모든 파일을 브라우저 메모리로 읽어 들여 검색하는 방식이라, 파일 몇천~몇만 개 수준의 폴더에서 **파일 내용까지** 찾고 싶을 때 적합합니다.
파일 *이름*만 찾고 싶고 드라이브 전체처럼 훨씬 큰 규모라면, [Everything](https://www.voidtools.com/) 같은 네이티브 파일 인덱서가 더 적합합니다.

This tool reads every matching file's content into the browser's memory, so it's best suited for searching **file contents** within a folder of up to a few tens of thousands of files. For filename-only search across an entire drive, a native indexer like [Everything](https://www.voidtools.com/) will be much faster.

## exe 빌드 방법 / Building the exe

`desktop/build_exe.bat` 실행 (PyInstaller 사용). 결과물은 `desktop/dist/FolderSearch.exe` + `desktop/dist/폴더검색.html`(같은 폴더에 자동으로 복사됨) — 이 두 파일은 항상 같이 다녀야 합니다.

Run `desktop/build_exe.bat` (uses PyInstaller). Output: `desktop/dist/FolderSearch.exe` + `desktop/dist/폴더검색.html` (auto-copied alongside it) - these two files must always travel together.

## 개인정보 / Privacy

모든 처리는 브라우저 안에서만 이루어집니다. 파일 내용이나 폴더 경로가 어디로도 전송되지 않습니다.

Everything runs entirely client-side in your browser. No file content or folder path is ever sent anywhere.

## 라이선스 / License

MIT

## Contributors

- [iamtalker](https://github.com/iamtalker)
- [Claude](https://claude.com/claude-code) (Anthropic) — pair-programmed the whole thing, from the first version through the performance rework and the exe packaging
