"""Ground model-selected phrases in literal user text, without trusting offsets."""
from copy import deepcopy
from astroquery_ai.runtime.errors import DomainError


def ground_spans(text, parsed):
    result, repairs = deepcopy(parsed), []
    for field in ("targets", "properties", "conditions", "unknown_fragments"):
        for index, item in enumerate(result[field]):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]:
                raise DomainError("PARSER_SPAN", "解析结果无法定位到用户原文", 502)
            start, end = item.get("start"), item.get("end")
            if type(start) is int and type(end) is int and 0 <= start < end <= len(text) and text[start:end] == item["text"]:
                continue
            # An exact, unique literal phrase has a deterministic location. This
            # corrects counting errors, not names/units/meaning or fuzzy matches.
            locations, cursor = [], 0
            while (position := text.find(item["text"], cursor)) >= 0:
                locations.append(position)
                cursor = position + 1
            if len(locations) != 1:
                raise DomainError("PARSER_SPAN", "解析片段未在原文唯一出现，请明确请求", 502)
            item["start"], item["end"] = locations[0], locations[0] + len(item["text"])
            repairs.append({"field": field, "index": index, "proposed": {"start": start, "end": end},
                            "actual": {"start": item["start"], "end": item["end"]}, "basis": "unique_exact_literal"})
    return result, repairs
