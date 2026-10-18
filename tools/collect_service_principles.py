"""Collect OCR signals and explicitly reviewed service principle summaries.

Only the curated summaries below have been checked against source page images.
OCR signals are discovery metadata, not verified instructions. Numeric service
specifications stay in the unmodified source pages.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def principle(label, text, heading="", scope="해당 원문 페이지"):
    return {"label": label, "text": text, "source_heading": heading,
            "scope": scope}


def build():
    pages = {}
    inputs = sorted((ROOT / "work/ocr_text").glob("*.json"))
    signals = {
        "위험": r"위험", "경고": r"경고", "주의": r"주의",
        "유의": r"유의", "필수": r"반드시|필히", "금지": r"금지|해서는안|해서는안된|하지못|절대",
        "조건부": r"필요시|경우.*교환|손상.*교환", "권고": r"권한다|권장|권고",
        "점검": r"확인한다|점검한다",
    }
    for path in inputs:
        source, number = path.stem.rsplit("__", 1)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        text = re.sub(r"\s+", "", data["text"])
        found = [label for label, pattern in signals.items() if re.search(pattern, text)]
        if found:
            key = f"{source}.pdf#{int(number)}"
            pages[key] = {"file": source + ".pdf", "page": int(number),
                          "signals": found, "principles": [], "completion": [],
                          "visual_verified": False,
                          "verification_scope": "OCR 신호만 수집. 요약문 미작성."}

    def add(stem, pp=(), cc=(), scope="해당 원문 페이지", heading="참고"):
        source, number = stem.rsplit("__", 1)
        key = f"{source}.pdf#{int(number)}"
        entry = pages.setdefault(key, {"file": source + ".pdf", "page": int(number), "signals": []})
        entry["principles"] = list(pp)
        entry["completion"] = [{"text": text, "source_heading": heading, "scope": scope} for text in cc]
        entry["visual_verified"] = True
        entry["verification_scope"] = "이 페이지에서 수록한 요약 문장만 원본 이미지와 대조함. 페이지 전체의 정비 적합성 검증을 뜻하지 않음."
        entry["verified_image"] = f"{stem}.png"
        for p in pp:
            if p["label"] not in entry["signals"]:
                entry["signals"].append(p["label"])
        if cc and "완료 확인" not in entry["signals"]:
            entry["signals"].append("완료 확인")

    # Forty-one source page warning blocks were visually reviewed in top_01..11.
    common_stems = """24-2 25-2 26-2 29-2 30-2 31-2 32-2 33-2 34-2 38-2 39-2 40-2 41-2 42-4 43-2 44-2 45-3 45-5 45-7 46-4 46-7 47-2 48-2 49-2 50-2 51-2 52-4 53-3 54-3 55-2 57-2 58-2 59-2 60-2 61-2 62-2 63-2 64-2 65-3 66-3 67-2""".split()
    for stem in common_stems:
        pp = [principle("주의", "손을 다치지 않도록 장갑을 착용한다.", "주의", "탈거")]
        if stem in {"38-2", "41-2"}:
            pp.append(principle("유의", "스크류 드라이버 또는 리무버에 보호 테이프를 감아 부품 손상을 방지한다.", "유의", "탈거"))
        elif stem == "40-2":
            pp.append(principle("유의", "테일게이트와 바디면에 손상을 주지 않도록 주의한다.", "유의", "탈거"))
        else:
            pp += [principle("유의", "리무버로 탈거할 때 부품이 손상되지 않도록 주의한다.", "유의", "탈거"),
                   principle("유의", "트림과 패널에 손상을 주지 않도록 주의한다.", "유의", "탈거")]
        add(stem + "__01", pp)

    # General service principles. Application conditions are intentionally retained.
    add("13__01", [
        principle("원문 원칙", "도장면과 내장 부품을 작업 커버와 테이프로 보호한다.", "일반 주의사항", "일반 정비"),
        principle("원문 원칙", "고장 원인과 탈거·분해 필요성을 판단한 뒤 정비 지침서 순서대로 작업한다.", "일반 주의사항", "일반 정비"),
        principle("필수", "볼트·너트를 교환할 때는 지정 규격품을 사용한다.", "일반 주의사항", "볼트·너트 교환")],
        ["후드를 닫기 전에 엔진룸에 공구와 부품이 남아 있는지 확인한다."], "후드 닫기 전", "주의")
    add("13__02", [
        principle("필수", "특수공구 사용을 지시한 작업에는 해당 특수공구를 사용한다.", "일반 주의사항", "특수공구 지정 작업"),
        principle("필수", "원문에서 지정한 재사용 금지 부품은 탈거 시 신품으로 교환한다.", "일반 주의사항", "원문 지정 부품 탈거")])
    add("13__03", [
        principle("필수", "부품을 교환할 때는 현대 순정 부품을 사용한다.", "부품", "부품 교환"),
        principle("권고", "보수용 세트·키트 부품의 사용을 권한다.", "부품", "보수용 부품 선택"),
        principle("원문 원칙", "보수용 부품이 차량 장착품과 다를 수 있으므로 부품 카탈로그를 확인한다.", "부품", "부품 교환")])

    for stem in ["46-5__01", "57-3__01"]:
        add(stem, [principle("필수", "도어 트림 탈거 후 재장착 시 클립(파스너)은 반드시 교환한다.", "참고", "트림 재장착")],
            ["글라스가 정상적으로 작동하는지 확인한다.", "도어의 열고 닫힘이 정상적인지 확인한다.", "커넥터를 확실히 조립한다."], "트림 장착 후")
    for stem in ["55-3__01", "67-3__01"]:
        add(stem, [principle("조건부", "프레임 가니쉬를 탈거한 뒤 부품 손상이 있을 경우 신품으로 교환한다.", "참고", "프레임 가니쉬 장착"),
                   principle("조건부", "프레임 몰딩을 탈거한 뒤 부품 손상이 있을 경우 신품으로 교환한다.", "참고", "프레임 몰딩 장착")])

    add("37-2__01", [principle("원문 원칙", "테일게이트를 탈거할 때는 두 사람 이상이 함께 작업한다.", "참고", "테일게이트 어셈블리 탈거"),
                            principle("유의", "테일게이트와 바디면에 손상을 주지 않도록 주의한다.", "유의", "테일게이트 어셈블리 탈거")])
    add("35-4__06", [principle("필수", "PTG의 초기화·설정은 진단 장비로 할 수 없으며 반드시 수동 조작한다.", "주의", "PTG 초기화 및 학습값 저장"),
                            principle("원문 원칙", "추가 절차는 진단 기기의 설명에 따라 진행한다.", "참고", "진단 기기 사용")])
    add("35-4__07", [principle("필수", "PTG 유닛 또는 PTG에 영향을 주는 부품 교환 시 초기화 순서에서 반드시 테일게이트를 수동으로 닫는다.", "초기화 및 학습 값 저장", "PTG 초기화")])
    add("35-4__08", [principle("금지", "파라미터 값 저장 과정 중 테일게이트를 잡거나 정지시키지 않는다.", "주의 사항", "PTG 학습값 저장"),
                            principle("필수", "테일게이트가 열린 상태에서 PTG 전원을 제거하거나 배터리를 탈·장착한 경우 모듈을 반드시 초기화한다.", "주의", "PTG 전원·배터리 탈장착")])
    add("42-3__01", [principle("필수", "신품 파워 테일게이트 유닛 교환 시 고장코드 유무를 반드시 확인한다. 잔존 코드별 조치는 원문을 따른다.", "참고", "PTG 유닛 교환 후 조정"),
                            principle("유의", "진단 기기 사용 시 원문의 차량 전원 상태를 유지하고 배터리 방전에 유의한다.", "유의", "진단 기기 사용")])
    add("42-5__01", [principle("조건부", "신품 PTG 유닛 교환 시 고장코드 확인·베리언트 코딩·초기화를 원문의 참조 순서에 따라 수행한다.", "주의", "신품 PTG 유닛 교환"),
                            principle("조건부", "OTA 대상 제어기 교체 시 진단 기기로 소프트웨어를 업데이트한다.", "주의", "OTA 대상 제어기 교체")],
        ["테일게이트의 열림과 닫힘이 정상적인지 점검한다.", "고객 인도 전 파워 테일게이트를 작동시켜 경보음이 표출되지 않는지 반드시 확인한다."], "PTG 유닛 장착 후")
    pages["42-5.pdf#1"]["completion"][1]["source_heading"] = "주의"
    add("42-6__02", [principle("주의", "베리언트 코딩 기능 수행 중 다른 기능이 동작하지 않도록 주의한다.", "진단 기기 화면 안내", "베리언트 코딩")])
    add("43-2__03", [principle("유의", "고정 클립이 손상될 수 있으므로 완전히 탈거하지 않는다.", "유의", "PTG 드라이브 유닛 고정 클립 분리")])
    add("43-2__04", [principle("유의", "드라이브 유닛 탈거 시 테일게이트가 닫힐 수 있으니 주의한다.", "유의", "PTG 드라이브 유닛 탈거")])
    add("46-2__01", [principle("조건부", "글라스런 판넬의 손상을 확인하고 필요 시 교환한다.", "참고", "프런트 도어 글라스 조정")])
    for stem in ["46-2__02", "56-2__02"]:
        add(stem, [principle("주의", "글라스 면이 손상되지 않도록 주의한다.", "주의", "글라스 조정")],
            ["글라스가 정상적으로 작동하는지 확인한다.", "스트라이커 조정 후 도어 개폐가 정상적인지 확인한다."], "각 조정 완료 후", "본문")
    add("46-2__03", [], ["도어 조정 후 도어와 바디의 간격이 일정한지 확인한다."], "도어 조정 완료 후", "본문")
    add("47-2__02", [principle("주의", "윈도우 글라스 탈거 시 글라스 면이 손상되지 않도록 주의한다.", "주의", "글라스 탈거")])
    for stem in ["47-3__01", "59-3__01"]:
        add(stem, [principle("조건부", "필요 시 글라스를 조정한다.", "참고", "글라스 장착 후")], ["글라스의 작동이 정상적인지 확인한다."], "글라스 장착 후")
    add("46-8__01", [principle("원문 원칙", "아웃사이드 핸들 장착 시 핸들 패드를 제 위치에 장착한다.", "참고", "아웃사이드 핸들 장착")],
        ["조립 후 들뜸이 없게 장착한다.", "도어의 열고 닫힘이 정상적인지 확인한다."], "아웃사이드 핸들 장착 후")

    # These instructions stay local to high-voltage source pages; never common.
    for stem in ["1__01", "14__01"]:
        add(stem, [principle("위험", "고전압 시스템 작업 전에 원문의 안전 지시를 반드시 준수한다.", "위험", "고전압 시스템 작업"),
                   principle("경고", "보호 장비를 착용한 담당자 외에는 고전압 관련 부분을 만지지 못하도록 한다.", "경고", "고전압 시스템 작업"),
                   principle("필수", "고전압 커넥터 분리 후 화재 방지를 위해 주변 냉각수 등을 반드시 제거한다.", "주의", "고전압 커넥터 분리")])
    for stem in ["1__03", "14__03"]:
        add(stem, [principle("필수", "고전압 작업 전 시계·반지 등 금속성 물질을 몸에서 반드시 제거한다.", "본문", "고전압 시스템 작업"),
                   principle("원문 원칙", "고전압 관련 작업 전 개인 보호 장비를 착용한다.", "본문", "고전압 시스템 작업"),
                   principle("필수", "고전압 시스템 점검·정비 전 반드시 고전압 차단 절차를 수행한다.", "본문", "고전압 시스템 작업")])
    for stem in ["5__01", "18__01"]:
        add(stem, [principle("경고", "고전압 관련 작업 시 원문의 안전·주의·경고를 숙지하고 차단 절차에 따라 반드시 고전압을 먼저 차단한다.", "경고", "고전압 차단")])
    for stem in ["5__04", "18__04"]:
        add(stem, [principle("필수", "고전압 차단 스위치 분리 후에는 원문에 지정된 방전 대기시간을 반드시 지킨다.", "경고", "고전압 차단 스위치 분리 후")])

    common = []
    for key in ["13.pdf#1", "13.pdf#2", "13.pdf#3"]:
        for p in pages[key]["principles"]:
            common.append({**p, "file": pages[key]["file"], "page": pages[key]["page"], "visual_verified": True})
    stats = {"source_pages_scanned": len(inputs), "signal_pages": len(pages),
             "summary_verified_pages": sum(p["visual_verified"] for p in pages.values()),
             "signal_only_pages": sum(not p["visual_verified"] for p in pages.values()),
             "principle_count": sum(len(p["principles"]) for p in pages.values()),
             "completion_count": sum(len(p["completion"]) for p in pages.values()),
             "labels": dict(Counter(x["label"] for p in pages.values() for x in p["principles"]))}
    return {"schema_version": 1, "purpose": "원문을 바꾸지 않는 정비 원칙 분류 보조",
            "summary_policy": "시각 확인한 핵심 문장만 요약. 수치·토크·대기시간은 변경 없이 원문 참조. 고전압·사고차·진단 등 적용 범위는 해당 원문 절차에 한정.",
            "signals_policy": "signals는 OCR 검색 신호다. 미검증 페이지의 지시 문장이나 강도를 확정하는 근거로 사용하지 않는다.",
            "common": common, "pages": pages, "statistics": stats,
            "visual_review": {"method": "원본 PNG 전체 또는 주의 상자 크롭을 직접 시각 대조", "contact_sheets": [f"reports/service_principles_visual/top_{i:02d}.png" for i in range(1, 12)]}}


if __name__ == "__main__":
    result = build()
    target = ROOT / "work/service_principles.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["statistics"], ensure_ascii=False, indent=2))
