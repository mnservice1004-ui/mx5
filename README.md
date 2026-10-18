# 정비교육 책자 편집 프로젝트

기존 정비매뉴얼을 근거로 부품 사진·작업 소개, 작업 길잡이, 참조절차와 복귀 안내가 있는 인쇄용 책자를 관리합니다. 프로젝트 폴더명만으로 차량의 정확한 차종·연식·세부사양을 확정하지 않습니다.

## VS Code에서 시작

1. `정비매뉴얼.code-workspace`를 엽니다.
2. Python 인터프리터는 `.venv\Scripts\python.exe`를 사용합니다.
3. `터미널 → 작업 실행`에서 `정비책자:`로 시작하는 작업을 선택합니다.
4. 먼저 **프로젝트 상태 확인**, 이어서 **기존 교육판 전체 검증**을 실행합니다.

기본 빌드 작업 `Ctrl+Shift+B`는 별도 작업본을 만듭니다. 기존 교육판 PDF·ZIP은 그대로 유지합니다.

## 파일 위치

| 위치 | 역할 |
|---|---|
| `inputs/정비매뉴얼.zip` | 원본 압축파일 복사본 |
| `work/source/` | 원본 PDF 149개 |
| `work/ocr_text/`, `work/ocr_bounds/` | 원문 검색과 위치 확인용 OCR 자료 |
| `work/education_structure_recommendation.json` | 책자별 작업 소개·학습 범위·안내 문구 |
| `work/education_frontmatter.py` | 부품 사진이 있는 첫장과 한 쪽 작업 길잡이 |
| `work/education_body_layout.py` | 본문 제목·참조·복귀 안내 배치 |
| `work/education_index_style.py` | 종합 색인 디자인 |
| `work/build_education_booklets.py` | PDF·ZIP 제작 |
| `work/verify_education_booklets.py` | 원문 보존·쪽번호·참조/복귀·링크·압축파일 검증 |
| `outputs/정비매뉴얼_교육교재_개선본/` | 복사해 보존한 이전 교육판: 본책 30개와 종합 색인 3개 |
| `outputs/정비매뉴얼_좌측제본_쪽번호정렬본/` | 현재 제작기가 읽는 기준 PDF 33개 |
| `outputs/작업중_교육교재/` | 전체 빌드 작업으로 새로 만드는 작업본 |
| `reports/` | 이 프로젝트에서 실행한 검사·미리보기·복사 기록 |
| `docs/previous_reports/` | 이전 폴더에서 가져온 과거 검증 기록 |
| `docs/제작기준.md`, `docs/다음작업.md` | 유지할 제작 기준과 아직 적용하지 않은 개선 과제 |

공구·교환 부품 요약과 정비 원칙 강조는 **다음 편집 과제**입니다. 기존 PDF를 복사했다는 사실이 이 개선 사항까지 반영했다는 뜻은 아닙니다.

## 터미널 명령

프로젝트 루트의 PowerShell에서 실행합니다.

```powershell
# 환경·입력·기존 결과물의 해시 확인
.\.venv\Scripts\python.exe tools/project.py doctor

# 보존한 교육판의 전체 구조·참조·복귀·쪽번호·ZIP 검증
.\.venv\Scripts\python.exe tools/project.py verify

# 프런트 도어 트림 시안 + 종합 색인 3개 제작, 이어서 검증
.\.venv\Scripts\python.exe tools/project.py pilot --books 07-02
.\.venv\Scripts\python.exe tools/project.py verify --edition pilot

# 전체 작업본: 30개 본책 + 색인 3개 + ZIP 3개
.\.venv\Scripts\python.exe tools/project.py build
.\.venv\Scripts\python.exe tools/project.py verify --edition draft

# 책자와 원본의 특정 페이지를 PNG로 확인
.\.venv\Scripts\python.exe tools/project.py preview --book 07-02 --page 2
.\.venv\Scripts\python.exe tools/project.py preview-source --file 13.pdf --page 1
```

시안은 `work/education_pilot/`에 저장됩니다. 각 작업을 다시 실행하면 해당 작업본과 검사 보고서를 갱신합니다. 디자인을 수정한 뒤에는 해당 페이지를 이미지로 확인하고, 참조 시작·복귀·쪽번호를 다시 검증합니다.

기존 전체 렌더 검증은 `tools/project.py render`로 실행할 수 있습니다. 이 명령은 기존 교육판 전체를 대상으로 하며 미리보기 한 장보다 시간이 오래 걸립니다.

## Python 환경

현재 PC에서는 기존 제작에 사용한 Python 3.12 런타임의 설치 라이브러리를 공유하는 `.venv`를 구성합니다. 이 방식은 추가 다운로드가 필요 없습니다. 재현에 필요한 버전은 `requirements.txt`에 기록했습니다.

다른 PC에서 새 환경을 만드는 경우에는 다음 명령을 사용합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Windows의 맑은 고딕 일반·굵은 글꼴이 필요합니다. 참고 교육교재 PDF의 외부 위치는 `project.json`에 기록하며, 기존 교육판 재제작에 그 대용량 참고 PDF를 복사할 필요는 없습니다.

프로젝트 폴더 전체를 다른 위치로 옮긴 경우, 원본·기준 PDF·표지 이미지도 함께 보존한 상태에서 `tools/project.py relocate`를 한 번 실행해 JSON의 내부 경로를 맞춥니다. 원본 PDF와 ZIP 내용은 변경하지 않습니다.

## 검증과 변경 관리

- 복사 기록 `reports/import_manifest.json`에 파일별 원본 해시가 있습니다. 복사본의 JSON 경로를 현재 프로젝트로 맞춘 경우에는 변경 후 해시도 별도로 기록합니다.
- 현재 전체 검증기는 이전 판본의 **33 PDF·1,092쪽** 등 집계값도 확인합니다. 새 페이지나 링크를 추가할 때는 새 설계에 맞는 예상값과 실제 검증 근거를 함께 갱신해야 합니다.
- 코드·설정·편집 데이터·제작 기준은 Git으로 관리할 수 있습니다. 원본 미디어, PDF·ZIP 결과물, 가상환경과 대용량 캐시는 `.gitignore`로 제외했습니다. 이 파일들은 로컬 프로젝트 안에 보존됩니다.
- 작업 완료 시 필요한 검증을 마친 뒤 Git 커밋과 원격 저장소 push를 수행합니다. 연결할 원격 주소가 없는 경우 로컬 커밋을 먼저 완료하고 저장소 주소를 확인합니다. 상세 지침은 `AGENTS.md`에 있습니다.
