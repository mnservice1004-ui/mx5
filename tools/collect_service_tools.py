"""Rebuild the curated, visually reviewed tools/parts evidence dataset.

This is an evidence transcription, not an OCR-to-instruction classifier. The
allowlists below contain only source regions actually inspected on 2026-10-18.
Source PDF hashes in the existing output prevent a later rebuild from silently
carrying the visual review over to changed source files. New findings need a new
visual review and an explicit edit of the curated definitions.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "work/service_tools_parts.json"
PAGES: dict[str, dict] = {}

# The original image crops for every page in these lists were actually opened
# and read. Do not extend a list solely because another OCR page looks similar.
ORDINARY_REVIEWED = """
24-2 25-2 26-2 29-2 30-2 31-2 32-2 33-2 34-2 38-2
39-2 40-2 41-2 42-4 43-2 44-2 45-3 45-5 45-7 46-4
46-7 47-2 48-2 49-2 50-2 51-2 52-4 53-3 54-3 55-2
57-2 58-2 59-2 60-2 61-2 62-2 63-2 64-2 65-3 66-3 67-2
""".split()
DIAGNOSTIC_REVIEWED = {
    "35-3": [1, 2, 3], "35-4": [4, 5, 6],
    "42-2": [1, 2, 3], "42-3": [1, 2], "42-5": [1], "42-6": [2],
    "52-3": [1, 2, 3], "53-2": [1, 2, 3], "54-2": [1, 2, 3],
    "65-2": [1, 2, 3], "66-2": [1, 2, 3],
}


def page(stem: str, number: int = 1) -> dict:
    key = f"{stem}.pdf#{number}"
    if key not in PAGES:
        pdf = ROOT / "work/source" / f"{stem}.pdf"
        PAGES[key] = {
            "file": f"{stem}.pdf", "page": number, "tools": [], "parts": [],
            "visual_verified": True,
            "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "verification": {
                "method": "original source image region visually inspected",
                "reviewed_on": "2026-10-18",
                "source_image": f"{stem}__{number:02d}.png",
            },
        }
    return PAGES[key]


def region(stem: str, number: int, pattern: str) -> dict:
    """Coordinates locate the supporting printed text, not a guessed tool size."""
    data = json.loads((ROOT / "work/ocr_bounds" / f"{stem}__{number:02d}.json").read_text(encoding="utf-8-sig"))
    hits = [b for b in data["boxes"] if re.search(pattern, b["text"])]
    if not hits:
        return {"source_top": 0.0, "source_bottom": 841.0}
    # All 383 source media boxes were inspected: 595 x 841 PDF points.
    scale = 841.0 / data["image_height"]
    return {
        "source_top": round(max(0, min(b["y"] for b in hits) - 6) * scale, 2),
        "source_bottom": round(min(data["image_height"], max(b["y"] + b["height"] for b in hits) + 6) * scale, 2),
        "evidence_text": [b["text"] for b in hits],
    }


def tool(stem: str, text: str, kind: str, purpose: str, *, number: int = 1,
         pattern: str = "", scope_note: str = "", specification=None,
         tool_number=None, status: str = "원문 확인") -> None:
    row = {
        "text": text, "kind": kind, "purpose": purpose, "status": status,
        "specification": specification, "tool_number": tool_number,
        "scope_note": scope_note,
    }
    row.update(region(stem, number, pattern) if pattern else {"source_top": 0.0, "source_bottom": 841.0})
    page(stem, number)["tools"].append(row)


def part(stem: str, text: str, condition: str, *, number: int = 1,
         pattern: str = "", kind: str = "조건부 교환", scope_note: str = "") -> None:
    row = {
        "text": text, "condition": condition, "kind": kind,
        "status": "차대번호로 품번 확인 필요", "part_number": None,
        "quantity": None, "scope_note": scope_note,
    }
    row.update(region(stem, number, pattern) if pattern else {"source_top": 0.0, "source_bottom": 841.0})
    page(stem, number)["parts"].append(row)


def collect() -> dict:
    PAGES.clear()
    for stem in ORDINARY_REVIEWED:
        if stem not in {"38-2", "41-2", "40-2"}:
            tool(stem, "리무버", "일반공구", "해당 부품 탈거", pattern="리무버",
                 scope_note="해당 탈거 절차의 원문 지시. 세부 규격은 미기재.")
        if stem in {"38-2", "41-2"}:
            tool(stem, "스크류 드라이버 또는 리무버", "일반공구", "해당 부품 탈거", pattern="드라이버|리무버",
                 scope_note="원문은 두 공구를 선택 관계로 제시. 팁 종류와 치수는 미기재.")
            tool(stem, "보호 테이프: 탈거 공구에 감아 사용", "보호준비물", "공구에 의한 부품 손상 방지", pattern="보호 테이프")
        tool(stem, "장갑", "보호준비물", "손 부상 방지", pattern="장갑")
    tool("45-3", "얇은 공구: 도어 커버 잠금핀 해제용", "일반공구", "연료 주입 도어 커버 잠금핀 해제",
         pattern="얇은 공구", scope_note="2단계에 명시된 공구. 형태·치수·품번 미기재.")

    for stem, numbers in DIAGNOSTIC_REVIEWED.items():
        for number in numbers:
            purpose = "해당 고장진단 절차의 코드·데이터·작동 확인"
            text = "진단 기기: 해당 고장진단 시"
            note = "해당 점검 절차에 적용. 기기 모델·공구번호는 원문 미기재."
            if stem == "35-3":
                purpose = "파워 테일게이트 시스템 고장코드·스위치 상태 확인"
                text = "진단 기기: 파워 테일게이트 고장진단 시"
            elif stem == "35-4" and number == 6:
                purpose = "진단 기기를 사용하는 PTG 모드 변경 절차의 후속 작업"
                text = "진단 기기: PTG 모드 변경 시"
                note = "이 쪽 앞부분의 모드 변경에만 적용. 뒤의 PTG 초기화·셋팅은 진단장비로 할 수 없으며 반드시 수동 조작하도록 원문이 명시."
            elif stem == "42-3":
                purpose = "파워 테일게이트 모드 변경"
                text = "진단 기기: PTG 모드 변경 시"
            elif stem == "42-5":
                purpose = "OTA 대상 제어기 교체 시 S/W 업데이트"
                text = "진단 기기: OTA 대상 제어기 교체 시"
                note = "OTA 대상 제어기 교체에만 적용. 원문은 미진행 시 OTA 자동 업데이트 불가를 명시."
            elif stem == "42-6":
                purpose = "신품 파워 테일게이트 유닛의 차량 사양별 배리언트 코딩"
                text = "진단 기기: PTG 유닛 교체 후 코딩 시"
                note = "파워 테일게이트 유닛을 신품 교체한 경우에 적용."
            tool(stem, text, "진단장비", purpose, number=number, pattern="진단.?기|진단.?장", scope_note=note)
            if stem == "35-4" and number == 6:
                # The later sentence is a prohibition on using this equipment.
                row = page(stem, number)["tools"][-1]
                first = region(stem, number, "추가적인 절차는 진단")
                row.update(first)

    for stem in ("1", "14"):
        for text, kind, purpose, pattern in [
            ("절연 공구: 고전압 시스템 작업용", "일반공구", "고전압 시스템 관련 작업", "절연 공구"),
            ("절연 덮개: 고전압 부품 차단용", "보호준비물", "작업과 연관되지 않은 고전압 시스템 차단", "절연 덮개"),
            ("절연 매트: 탈거 고전압 부품 보관용", "보호준비물", "탈거 고전압 부품의 누전 예방", "절연 매트"),
            ("절연 테이프: 분리 고전압 케이블 절연용", "보호준비물", "고전압 케이블 분리 직후 절연", "절연 테이프"),
        ]:
            tool(stem, text, kind, purpose, pattern=pattern,
                 scope_note="고전압 관련 작업에 적용. 일반 도어·트림 작업 전부의 필수 준비물로 일반화하지 않음.")

    for stem in ("2", "15"):
        for name in ("절연 장갑", "절연화", "절연복", "절연 안전모"):
            tool(stem, name + ": 고전압 부품 작업용", "보호준비물", "고전압 부품 점검 및 관련 작업 시 착용", pattern=re.escape(name),
                 specification="절연 성능 1000 V 이상" if name == "절연 장갑" else None,
                 scope_note="고전압 부품 점검 및 관련 작업에 한정. 원문에서 1000 V 이상 표기는 절연 장갑 행에만 있음.")
        for name, purpose, note in [
            ("보호 안경", "스파크 발생 가능 고전압 배터리 단자·와이어링 탈장착/점검 및 고전압 배터리 시스템 어셈블리 작업", "원문의 두 적용 조건에 해당하는 경우 착용."),
            ("안면 보호대", "스파크 발생 가능 고전압 배터리 단자·와이어링 탈장착/점검 및 고전압 배터리 시스템 어셈블리 작업", "원문의 두 적용 조건에 해당하는 경우 착용."),
            ("절연 매트", "탈거 고전압 부품 정리·보관", "고전압 부품 취급 시 감전 사고 예방용."),
            ("절연 덮개", "고전압 부품 차단", "보호 장비 미착용자의 감전 사고 예방용."),
            ("경고 테이프", "작업 차량 주변 접근 차단", "고전압 작업 중 차량 주변에 설치."),
        ]:
            tool(stem, name + ": 고전압 작업용", "보호준비물", purpose, number=2, pattern=re.escape(name), scope_note=note)

    for stem in ("3", "16"):
        for text, kind, purpose, pattern in [
            ("개인 보호 장비(PPE): 사고 차량 작업용", "보호준비물", "사고 차량 작업 및 취급", "개인 보호 장비"),
            ("붕소액: 사고 차량 준비물", "보호준비물", "원문 사고 차량 작업 준비사항", "붕소액"),
            ("이산화탄소 소화기 또는 별도 소화기", "보호준비물", "원문 사고 차량 작업 준비사항", "이산화탄소 소화기"),
            ("전해질용 수건", "보호준비물", "원문 사고 차량 작업 준비사항", "전해질용"),
            ("비닐 테이프: 터미널 절연용", "보호준비물", "터미널 절연", "비닐 테이프"),
            ("메가옴 테스터: 고전압 절연저항 확인용", "측정장비", "고전압 절연저항 확인", "메가옴 테스터"),
        ]:
            tool(stem, text, kind, purpose, pattern=pattern,
                 scope_note="사고 차량 작업 준비사항에만 적용. 소화·고전압 취급 방법은 원문 전체 주의사항을 함께 따름.")

    for stem in ("4", "17"):
        tool(stem, "전동식 컴프레서 전용 냉매 회수·충전기", "전용장비", "하이브리드 차량 냉매 회수·충전", pattern="전용 장비|전용의 냉매",
             scope_note="해당 하이브리드 차량 냉매 회수·충전 시에만 적용. 일반 차량 PAG 오일 혼입 금지. 기기 모델·냉매량은 이 항목에서 추정하지 않음.")
        tool(stem, "지정 냉매·냉동유(POE): 냉매 회수·충전 시", "작업자재", "전동식 컴프레서 냉매·냉동유 주입", pattern="지정된 냉매|POE 오일",
             scope_note="지정 냉매의 종류·양은 이 원문에 구체적으로 기재되지 않아 보완하지 않음.")

    tool("13", "작업 커버(시트 커버)·보호 테이프", "보호준비물", "도장면·내장 부품의 오손·손상 방지", pattern="작업 커버")
    tool("13", "보호 테이프: 와이어링 간섭부 보호용", "보호준비물", "부품 모서리·끝단과 간섭하는 와이어링 보호", number=7, pattern="테이프")
    tool("13", "회로 테스터: 커넥터 통전·전압 점검용", "측정장비", "커넥터 단자 통전·전압 확인", number=11, pattern="회로 테스터",
         scope_note="커넥터 점검 시에만 적용. 탐침 삽입 방향과 절연 손상 방지 원문을 함께 따름.")

    for name, code, purpose, pattern in [
        ("호그 링 클립 인스톨러", "09880-4F000", "호그 링 클립 장착", "09880|호그 링"),
        ("수직 측정기", "09964-C1200", "빌트인 캠 전방 카메라 보정 시 타겟 각도 측정", "09964|수직 측정기"),
        ("전방 카메라 보정용 지그", "09890-3V100", "빌트인 캠 전방 카메라 보정", "09890|보정용 지그"),
    ]:
        tool("22", f"{name} ({code})", "특수공구", purpose, pattern=pattern, tool_number=code,
             scope_note="특수공구 표의 명시 용도에만 적용. 차량 교환 부품번호가 아니며 모든 도어 작업의 필수 공구가 아님.")

    for stem, side in (("46-5", "프런트"), ("57-3", "리어")):
        part(stem, f"{side} 도어 트림 클립(파스너)", "도어 트림 탈거 후 재장착 시 반드시 교환", kind="필수 교환", pattern="클립.*파스너",
             scope_note="원문에 수밀·이탈 문제 예방 사유가 명시됨. 부품번호·수량은 미기재.")
    for stem, side in (("55-3", "프런트"), ("67-3", "리어")):
        for name in ("프레임 가니쉬", "프레임 몰딩"):
            part(stem, f"{side} 도어 {name}", "탈거 후 부품 손상이 있을 경우 신품 교환", pattern=name,
                 scope_note="손상 조건에 해당하는 부품만 교환. 가니쉬와 몰딩의 품번을 동일하다고 추정하지 않음.")
    for stem, side in (("46-2", "프런트"), ("56-2", "리어")):
        part(stem, f"{side} 도어 글라스런 판넬", "손상 여부를 확인하고 필요 시 교환", pattern="글라스런 판넬",
             scope_note="원문 글라스 조정의 사전 점검 조건. 일괄 필수 교환으로 해석하지 않음.")
    for name in ("오일 씰", "가스켓트", "패킹", "O-링", "록크 와셔", "분할 핀"):
        part("13", name, "해당 부품을 탈거했을 때 필히 신품 교환", number=2, kind="필수 교환",
             pattern="부품을 탈거|" + re.escape(name), scope_note="일반 정비 원칙. 실제로 해당 부품을 탈거하는 작업에만 적용하며 모든 도어 작업에 이 부품이 사용된다는 의미가 아님.")

    # Fault-table rows preserve the symptom/cause and any alternative to
    # replacement. A diagnostic possibility must never become a shopping list
    # of mandatory parts.
    def fault(stem, name, condition, number=1):
        part(stem, name, condition, number=number,
             scope_note="고장진단표의 해당 현상·원인 확인 후 적용. 진단 전 일괄 교환 또는 무조건 교환 지시가 아님.")
    fault("19", "도어 아웃벨트", "도어 주위 풍절음의 원인이 아웃벨트 스킨립 들뜸일 때 교체")
    fault("19", "선루프 웨더 스트립", "선루프 누수의 원인이 웨더 스트립 오장착·변형일 때 교체")
    fault("19", "선루프 디플렉터", "선루프 바람소리의 원인이 디플렉터 변형·이탈일 때 교체 또는 재장착")
    fault("19", "선루프 모터", "작동 케이블·피니언 맞물림 불량 시 위치 조정 또는 교체; 피니언 기어 마모·파손 시 교체")
    fault("19", "선루프 롤러 블라인드", "스프링 내부 소음·텐션 풀림 시 교체; 테프론 가이드 이탈 시 재조립 또는 교체")
    fault("19", "선루프 메커니즘 레일", "레일 이물질 퇴적으로 작동 부하 증가 시 원문 조치 순서에 따라 청소·그리스 도포와 모터 조정/교체 후 레일 교체 판단")
    fault("19", "선루프 프런트·무빙 글라스", "외부 충격으로 파손된 해당 글라스를 교체")
    fault("19", "도어 글라스 모터·레귤레이터", "모터 고장 또는 레귤레이터 파손·변형이 확인되면 수정 또는 교환")
    fault("19", "도어 핸들·랫치·체커", "도어 개폐 불량의 원인이 해당 부품의 파손·변형·장착 불량인 경우 수정 또는 교환")
    fault("19", "와이퍼 고무", "와이퍼 닦임·떨림·소음의 원인이 고무 마모인 경우 신품 교체", number=2)
    for text, purpose, number in [
        ("실리콘 오일", "선루프 웨더 스트립 비빔 소음 시 도포", 1),
        ("그리스", "선루프 메커니즘 레일 청소 후 도포 또는 도어 힌지·체커 그리스 부족 시 주유", 1),
        ("소음 발생부 패드", "선루프 커버·트림 간섭 소음 부위 부착", 1),
        ("씰런트", "윈드쉴드·리어 윈도우 누수 원인이 실 파손인 경우 도포", 2),
        ("깨끗한 물수건", "오염된 글라스·와이퍼 블레이드 청소", 2),
        ("공구: 와이퍼 블레이드 유격 조치용", "와이퍼 블레이드 유격 시 좌우측을 눌러 조치", 2),
    ]:
        tool("19", text, "일반공구" if text.startswith("공구") else "작업자재", purpose, number=number,
             scope_note="바디 고장진단표의 해당 현상·원인 조건에서만 적용. 제품 규격·품번·양은 미기재.")
    fault("35-3", "테일게이트 랫치 어셈블리", "갑작스러운 열림의 원인이 랫치 이상인 경우 배선·고장코드 확인 후 필요 시 교체")
    fault("35-3", "테일게이트 랫치 어셈블리", "Primary/Secondary 위치에서 파워래칭 불가·랫치 이상일 때 배선·코드·진단 확인 후 필요 시 교체", number=2)
    fault("35-3", "바디 도메인 컨트롤 유닛(BDC)", "전동 잠금해제 불가·BDC 이상일 때 차체 점검 매뉴얼에 따라 진단하고 필요 시 교체", number=3)
    fault("35-3", "무선 리모트키", "전동 잠금해제 불가·리모트키 이상일 때 프로그램 재작성 후 필요 시 교체", number=3)
    fault("35-3", "테일게이트 모터 어셈블리", "전동 잠금해제 불가·모터 이상일 때 이물질·배선 확인 후 클러치가 붙지 않으면 어셈블리 교체; 진단 후 필요 시 모터 교체", number=3)
    fault("35-3", "테일게이트 완전 개방 스위치", "전동 잠금해제 불가·모터 이상 진단에서 완전 개방 스위치가 작동하지 않으면 필요 시 교체", number=3)
    fault("35-3", "테일게이트 가스 스트럿", "열린 상태 유지 불가 또는 개폐 작동력 과다의 원인이 가스 스트럿 이상이면 교체하고 부착물 파손 확인", number=3)
    fault("35-3", "테일게이트 가스 스트럿", "테일게이트가 매우 느리게 열리고 가스 스트럿 이상이 확인되면 필요 시 교체", number=4)
    fault("35-3", "테일게이트 모터 어셈블리", "테일게이트가 매우 느리게 열리고 모터 어셈블리 이상이 확인되면 필요 시 교체", number=4)
    for number in (1, 2, 3, 4):
        fault("35-3", "간섭 부위의 해당 부품", "고장진단표의 구성요소 간 간섭이 확인된 경우 간섭 위치 재설정 또는 필요한 부품 교체", number=number)
    fault("35-3", "테일게이트 드라이브 유닛 관련 부품", "개폐 작동력 과다의 원인이 드라이브 유닛 고장·연결 해제 불가일 때 차체 점검 매뉴얼에 따라 진단 후 필요 시 교체", number=3)

    # A new PTG unit is a conditional input to these procedures, not an order
    # to replace a healthy unit merely because this page is opened.
    for stem, condition in (
        ("42-3", "신품 교환 후 고장코드를 확인하고 B24B0 잔존 시 파워 테일게이트 모드 변경"),
        ("42-5", "신품 교환 후 고장코드 확인(B24B0 잔존 시 모드 변경)·배리언트 코딩·초기화 진행"),
        ("42-6", "신품 교체 후 차량 사양에 맞는 배리언트 코딩 실시"),
    ):
        part(stem, "파워 테일게이트 유닛", condition, number=1,
             pattern="신품|교환|교체", kind="교환 후 절차",
             scope_note="이 페이지는 교환 판정 기준이 아니며, 단순 탈거·재장착을 신품 교체로 해석하지 않음.")

    old = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else None
    if old:
        for key, row in PAGES.items():
            previous = old.get("pages", {}).get(key)
            if previous and previous.get("source_pdf_sha256") != row["source_pdf_sha256"]:
                raise RuntimeError(f"Source changed; repeat the visual review before rebuilding: {key}")
    ordered = dict(sorted(PAGES.items(), key=lambda item: ([int(x) for x in item[1]["file"].removesuffix(".pdf").split("-")], item[1]["page"])))
    kinds = Counter(t["kind"] for p in ordered.values() for t in p["tools"])
    return {
        "schema_version": 1,
        "reviewed_on": "2026-10-18",
        "pages": ordered,
        "summary": {
            "ocr_pages_searched": 383, "source_files": 149,
            "pages_with_verified_entries": len(ordered),
            "tool_entries": sum(len(p["tools"]) for p in ordered.values()),
            "tool_kinds": dict(kinds),
            "part_entries": sum(len(p["parts"]) for p in ordered.values()),
            "confirmed_vehicle_part_numbers": 0,
            "confirmed_special_tool_numbers": 3,
        },
        "notes": [
            "Only actually viewed original source image regions are marked visual_verified. OCR was used to search all 383 pages; a search miss does not establish global absence.",
            "Source coordinates are PDF points from the top of the original page, derived from OCR bounding boxes; source_top/source_bottom bound the evidence, not an equipment dimension.",
            "Source region contact sheets used for this review are in work/tools_parts_audit/service_review. Full source images were read from the preserved previous workspace; the evidence remains linked by source file, page and PDF SHA-256.",
            "No orderable vehicle replacement part number, replacement quantity or unspecified driver/socket size was inferred. part_number and quantity remain null. VIN-based WPC/catalogue confirmation has not been performed.",
            "09880-4F000, 09964-C1200 and 09890-3V100 are SST tool numbers only. Their presence in the common tool table does not require them for every door procedure.",
            "A dash in an SST/equipment guide column is not evidence that no tools are required. Hardware names and drawing callouts A/B are not tool sizes or orderable part numbers.",
            "Weatherstrip/glass-run clip diagrams in 49-2.pdf#1, 61-2.pdf#1 and 62-2.pdf#3 were inspected. The small red location dots are different from the no-reuse prohibition symbol in 12.pdf#1; no mandatory replacement instruction was inferred from those dots.",
            "The explicit mandatory clip replacement statements are 46-5.pdf#1 and 57-3.pdf#1. Garnish/moulding and glass-run-panel replacement retain their damage/need conditions.",
            "General replacement principles in 13.pdf#2 apply only when the listed part is actually removed. HV PPE, accident preparations and refrigerant equipment retain their special application scopes.",
            "Fault-table parts are diagnostic possibilities, not mandatory preparation quantities. Retain the symptom, verified cause, alternative adjustment/repair and source procedure when presenting them.",
            "PTG initialization/settings on 35-4.pdf#6 are manual per source; its diagnostic tool entry is restricted to the preceding mode-change segment.",
            "Original text, figures, numeric values and application conditions remain the governing instructions; this file provides a concise navigation/preparation layer only.",
        ],
    }


if __name__ == "__main__":
    result = collect()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
