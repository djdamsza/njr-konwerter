"""Podpowiedź pisowni dla grup ujednolicenia. Model wybiera jedną formę z listy."""
from __future__ import annotations

import json


def advice_prompt(groups: list[dict]) -> str:
    lines = []
    for group in groups:
        variants = [str(name).strip() for name in (group.get("variants") or []) if str(name).strip()]
        if len(variants) < 2:
            continue
        field = group.get("field") or "author"
        lines.append(f'{group.get("gi")}\t{field}\t{" | ".join(variants)}')
    return (
        "Każda linia to grupa zapisów, które program uznał za tę samą nazwę. "
        "Wskaż jedną prawidłową pisownię z tej listy: wielkość liter, polskie znaki, myślnik jak w IN-GRID. "
        "change to zapisy, które trzeba podmienić na keep. keep nie wpisuj do change. "
        "Gdy w grupie są różne utwory albo różne wersje, których nie wolno zrównać, oddaj change: []. "
        "Nie wymyślaj pisowni spoza listy. "
        "Odpowiedź to sam JSON: "
        '[{"gi": 1, "keep": "The Buggles", "change": ["THE BUGGLES"], "why": "krótko"}].\n'
        "gi\tpole\tzapisy\n"
        + "\n".join(lines)
    )


def parse_normalize_advice(answer: str, allowed: dict[int, set[str]]) -> list[dict]:
    text = (answer or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            gi = int(item.get("gi"))
        except (TypeError, ValueError):
            continue
        names = allowed.get(gi)
        if not names:
            continue
        keep = str(item.get("keep") or "").strip()
        if keep not in names:
            continue
        change = []
        for raw in item.get("change") or []:
            name = str(raw or "").strip()
            if name in names and name != keep and name not in change:
                change.append(name)
        out.append({
            "gi": gi,
            "keep": keep,
            "change": change,
            "why": str(item.get("why") or "").strip(),
        })
    return out
