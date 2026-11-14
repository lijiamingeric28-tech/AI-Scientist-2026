"""Read declared time and band coordinates from the saved original table row."""

from astroquery_ai.runtime.codec import loads
from astroquery_ai.science.structured_quality import time_coordinate


def table_coordinates(record, evidence):
    epochs, bands = [], []
    for ref in record.get("evidence_refs", []):
        item = evidence.get(ref["id"], {})
        if item.get("text_origin") != "original_cells":
            continue
        try:
            row = loads(item["raw_text"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(row, dict) or not isinstance(row.get("cells"), dict):
            continue
        columns = row.get("columns") or []
        cells = row["cells"]
        locator = item.get("locator") or {}
        for column in columns:
            name = column.get("name")
            if not isinstance(name, str):
                continue
            ucd = column.get("ucd") or ""
            value = cells.get(name)
            label = {"column": name, "value": value, "unit": column.get("unit_text"),
                     "definition": column.get("description"), "evidence_id": ref["id"]}
            if value is not None and str(value).strip() and time_coordinate(column):
                if label not in epochs:
                    epochs.append(label)
            if value is not None and str(value).strip() and (
                "instr.filter" in ucd.split(";") or name.casefold() in {"band", "filt", "filter", "passband"}
            ):
                if label not in bands:
                    bands.append(label)
            elif name == locator.get("column"):
                tag = next((x for x in ucd.split(";") if x.startswith(("em.opt.", "em.UV.", "em.IR."))), None)
                if tag:
                    label.update(value=tag, unit=None)
                    if label not in bands:
                        bands.append(label)
    return {"epochs": epochs, "bands": bands}
