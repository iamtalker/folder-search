# 폴더검색 (Folder Search)

브라우저에서 로컬 폴더를 골라 그 안의 파일들을 (이름 + 내용까지) 검색하는 단일 HTML 파일 도구입니다.
서버나 설치 없이, 이 저장소의 `폴더검색.html` 파일 하나만 다운로드해서 브라우저로 열면 바로 씁니다.

A single self-contained HTML file that lets you pick a local folder in your browser and full-text search its files — no server, no install. Just download `폴더검색.html` and open it in your browser.

## 요구사항 / Requirements

- **Chrome 또는 Edge** (File System Access API를 사용합니다. Firefox/Safari는 아직 미지원)
- Chrome or Edge (uses the File System Access API; not yet supported in Firefox/Safari)

## 기능 / Features

- 📁 폴더 선택 후 하위 폴더까지 재귀적으로 스캔
- 검색어와 파일명/본문 일치 정도로 **관련도순** 정렬, **최신순** 정렬도 지원
- `AND` / `OR` / `NOT` + 괄호를 쓰는 불리언 검색 (`"정확한 구절"` 검색도 가능)
- 🔄 새로고침 버튼으로 폴더를 다시 읽어 최신 상태 반영
- 최근 사용한 폴더 여러 개를 기억해뒀다가 클릭 한 번으로 전환 (브라우저의 IndexedDB에 저장, 서버로 전송되는 데이터 없음)
- 권한 없는 시스템 폴더(`System Volume Information` 등)는 자동으로 건너뜀
- 대상 확장자 / 제외 폴더 이름을 직접 편집 가능

## 사용법 / Usage

1. `폴더검색.html`을 다운로드해서 더블클릭으로 엽니다 (Chrome/Edge).
2. "📁 폴더 선택"을 눌러 검색할 폴더를 고릅니다.
3. 검색창에 검색어를 입력합니다. 공백은 AND로 동작하고, `OR`/`NOT`과 괄호도 쓸 수 있습니다.
4. 폴더 내용이 바뀌었다면 "🔄 새로고침"을 눌러 다시 읽습니다.

## 왜 만들었나 / Why

모든 파일을 브라우저 메모리로 읽어 들여 검색하는 방식이라, 파일 몇천~몇만 개 수준의 폴더에서 **파일 내용까지** 찾고 싶을 때 적합합니다.
파일 *이름*만 찾고 싶고 드라이브 전체처럼 훨씬 큰 규모라면, [Everything](https://www.voidtools.com/) 같은 네이티브 파일 인덱서가 더 적합합니다.

This tool reads every matching file's content into the browser's memory, so it's best suited for searching **file contents** within a folder of up to a few tens of thousands of files. For filename-only search across an entire drive, a native indexer like [Everything](https://www.voidtools.com/) will be much faster.

## 개인정보 / Privacy

모든 처리는 브라우저 안에서만 이루어집니다. 파일 내용이나 폴더 경로가 어디로도 전송되지 않습니다.

Everything runs entirely client-side in your browser. No file content or folder path is ever sent anywhere.

## 라이선스 / License

MIT
