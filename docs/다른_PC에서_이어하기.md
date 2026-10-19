# 다른 Windows PC의 VS Code에서 이어서 작업하기

2026-10-19 인수인계 기준. GitHub 저장소에는 제작 코드·설정·편집 데이터와 상대 경로로 정리한 기준 목록이 들어 있다. 원본 ZIP, 원본 PDF, 표지·OCR 이미지, 보존판·통합판 PDF/ZIP 및 검토 기록은 Git 이력에서 제외하고 별도의 `mx5-handoff-state-2026-10-19.zip`에 보관한다. `.venv`와 대량 렌더 이미지는 새 PC에서 다시 만든다.

## 새 PC에서 시작

1. Windows에 Git, VS Code, Python 3.12를 설치한다. 맑은 고딕 일반·굵은 글꼴이 있어야 PDF 제작 환경 검사가 통과한다.
2. GitHub의 `mnservice1004-ui/mx5` 저장소를 새 PC의 **로컬 작업 폴더**에 복제한다. 현재 작업 브랜치는 `master`다. OneDrive 동기화 폴더 안에 Git 작업 폴더를 두면 두 PC의 Git 제어 파일이 충돌할 수 있으므로 별도 로컬 폴더를 권한다.
3. 같은 GitHub 계정으로 로그인하여 [게시되지 않은 인수인계 릴리스 초안](https://github.com/mnservice1004-ui/mx5/releases/tag/untagged-494cbc9cfed9e7802958)에서 `mx5-handoff-state-2026-10-19.zip`을 내려받는다. 초안은 저장소 쓰기 권한이 있는 계정에서 확인할 수 있다. 로컬 인수인계 파일이 OneDrive를 통해 이미 동기화되었다면 그 복사본을 사용해도 된다.
4. 아래 명령으로 ZIP의 파일별 SHA-256을 검사하고, Git에서 제외한 파일을 복원한다. 복원기는 기존 파일이 다르면 덮어쓰지 않고 멈춘다.

```powershell
git clone https://github.com/mnservice1004-ui/mx5.git C:\AIProjects\mx5
Set-Location C:\AIProjects\mx5
$handoffZip = Join-Path $env:USERPROFILE 'Downloads\mx5-handoff-state-2026-10-19.zip'
py -3.12 tools\handoff_bundle.py verify $handoffZip
py -3.12 tools\handoff_bundle.py restore $handoffZip --destination .
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\project.py relocate
.\.venv\Scripts\python.exe tools\project.py doctor
.\.venv\Scripts\python.exe tools\project.py verify --edition draft
.\.venv\Scripts\python.exe tools\project.py verify-service
git status --short --branch
code .\정비매뉴얼.code-workspace
```

예시의 `C:\AIProjects\mx5`는 새 PC에서 원하는 로컬 경로로 바꿀 수 있다. 인수인계 ZIP은 만들 당시의 Git 커밋을 기록한다. 복원기는 그 커밋 또는 **안내 문서와 복원기만 바뀐 후속 커밋**에서 작동하며, 제작 코드·근거 데이터가 달라졌다면 새 인수인계 ZIP을 요구한다. `relocate`는 ZIP 안의 작업본 목록 등 **Git에서 제외된** JSON에 남아 있는 이전 PC의 경로를 새 경로로 바꾼다. Git으로 관리하는 기준 목록은 이미 상대 경로이므로 이 단계 뒤 `git status`가 깨끗해야 한다.

`doctor`는 원본과 보존 교육판·기준판의 파일 해시와 제작 환경을 확인한다. `verify --edition draft`는 통합판의 원문·참조·복귀·색인·양면 쪽번호와 압축파일을 검사한다. `verify-service`는 새 준비물·정비 원칙 근거와 표시를 확인한다. 인수인계 ZIP의 기존 `reports/`는 이전 PC에서 수행한 검토 기록이다. 새 PC에서 책자를 변경한 뒤에는 해당 검증과 `tools/project.py render --edition draft`를 다시 실행하고 변경 페이지를 실제 이미지로 확인한다.

VS Code에서는 `정비책자:` 작업을 실행할 수 있다. 작업을 마치면 사용자 지시에 따라 변경한 코드·편집 데이터만 Git에 커밋하고 `origin/master`에 push한다. 원본·PDF·ZIP·가상환경은 Git에 추가하지 않는다. 다음 PC로 다시 옮길 때에는 최신 커밋에서 새 인수인계 묶음을 만들고 초안 릴리스에 보관한다.

## 이 PC에서 새 인수인계 묶음을 만들 때

프로젝트의 미커밋 변경을 검토·검증하고 커밋·push한 뒤 다음을 실행한다. 기존 묶음을 덮어쓰지 않도록 새 파일명을 지정한다.

```powershell
.\.venv\Scripts\python.exe tools\portable_manifest_paths.py --check
.\.venv\Scripts\python.exe tools\handoff_bundle.py create --archive handoff\mx5-handoff-state-새날짜.zip
.\.venv\Scripts\python.exe tools\handoff_bundle.py verify handoff\mx5-handoff-state-새날짜.zip
```

현재 릴리스 업로더의 `--handoff` 옵션은 이 판본의 `mx5-handoff-state-2026-10-19.zip`을 원격 초안에 백업한다. 후속 판본은 파일명·릴리스 설명·업로드 이름을 먼저 갱신한다. 인수인계 ZIP은 원본과 PDF를 포함하므로 Git 커밋에 넣지 않는다. 빌드 전용 원본 화면 383장과 파일별 해시를 포함하되, 재생성 가능한 전체 렌더 캐시와 PC별 가상환경은 제외한다.

`project.json`의 참고 교육교재 PDF 경로는 이전 PC의 외부 위치를 기록한 것이다. 기존 정비 책자의 제작·검증에는 그 파일이 필요하지 않다. 참고 PDF 자체를 새 PC에서 열어 비교하려면 별도로 복사한다.
