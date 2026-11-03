"""Small, read-only chat projections of facts already saved by scientific jobs."""
from collections import Counter


FINISHED = {"succeeded", "failed", "cancelled", "not_run"}

TERMINAL_TASKS = {"completed", "cancelled", "failed", "error", "budget_exhausted", "definition_invalidated"}
CONCLUDED_DECISIONS = {"supported", "not_applicable", "not_passed", "raw_retained"}


def quality_has_ended(events):
    """Use only transitions visible at this cursor, including quality revisits."""
    active = None
    visited = False
    lifecycle = None
    for event in events:
        payload = event["payload"]
        if event["kind"] == "execution_stage_changed":
            active = payload.get("stage_id")
            visited = visited or active == "quality"
        elif event["kind"] == "task_state_changed":
            lifecycle = payload.get("lifecycle")
    return lifecycle in TERMINAL_TASKS or visited and active != "quality"


def review_progress(get, jobs, events):
    decisions = get("quality_decision")
    latest = {}
    for decision in decisions:
        candidate_id = (decision.get("candidate_ref") or {}).get("id")
        if candidate_id:
            latest[candidate_id] = decision
    results = {result["root_id"]: result for result in get("quality_reextraction_result")}
    actions = get("quality_reextraction_action")
    links = get("quality_candidate_link")
    ended = quality_has_ended(events)
    parent_actions = {(action.get("parent_candidate_ref") or {}).get("id"): action for action in actions}
    reextractions = {}
    for action in actions:
        root_id = action["root_id"]
        result = results.get(root_id, {})
        own_links = [link for link in links if link["root_id"] == root_id]
        parents = {(link.get("parent_ref") or {}).get("id") for link in own_links}
        leaves = [link["candidate_ref"]["id"] for link in own_links
                  if link["candidate_ref"]["id"] not in parents]
        states = [latest.get(leaf, {}).get("state") for leaf in leaves]
        relevant_jobs = [job for job in jobs.values() if job["kind"] == "quality_reextract"
                         and job["payload"].get("root_id") == root_id]
        if result.get("outcome") == "no_target_result":
            state = "no_target_result"
        elif states and all(s in CONCLUDED_DECISIONS for s in states):
            state = "rechecked"
        elif any(s in {"technical_failure", "not_completed"} for s in states):
            state = "recheck_incomplete"
        elif result.get("complete"):
            state = "recheck_incomplete" if ended else "recheck_pending"
        elif ended:
            state = "not_completed"
        elif any(job["status"] == "running" for job in relevant_jobs):
            state = "running"
        elif any(job["status"] == "failed" for job in relevant_jobs):
            state = "failed"
        elif relevant_jobs:
            state = "waiting"
        else:
            state = "registered"
        reextractions[root_id] = {"state": state, "result": result, "decisions": states}
    return latest, parent_actions, reextractions, ended


def candidate_state(candidate, latest, parent_actions, reextractions, quality_ended):
    candidate_id = candidate["candidate_id"]
    decision = latest.get(candidate_id, {})
    action = parent_actions.get(candidate_id)
    if action:
        progress = reextractions[action["root_id"]]
        if progress["result"].get("complete"):
            return "reextracted"
        return "not_completed" if quality_ended else "reextraction_requested"
    if decision:
        state = decision["state"]
        if quality_ended and state in {"needs_human", "reextraction_requested"}:
            return "not_completed"
        return state
    return "conclusion_unrecorded" if quality_ended else "collected"


def text(value):
    if isinstance(value, list):
        return " · ".join(str(v) for v in value[:2])
    return str(value or "")


def recent(items, limit):
    # Keep running work visible. Stable object identities keep UI rows in place.
    active = [item for item in items if item.get("state") in {"running", "waiting", "acquiring"}]
    settled = [item for item in items if item not in active]
    return (active + list(reversed(settled)))[:limit]


def job_progress(items):
    return {
        "total": len(items),
        "finished": sum(item["state"] in FINISHED for item in items),
        "running": sum(item["state"] == "running" for item in items),
        "succeeded": sum(item["state"] == "succeeded" for item in items),
        "failed": sum(item["state"] == "failed" for item in items),
    }


def project(get, jobs, events, *, cursor, limit=5):
    """Jobs have their payload joined to the state visible at the event cursor."""
    works = {w["work_id"]: w for w in get("work")}
    sources = {s["source_id"]: s for s in get("source")}
    preparation = (get("material_preparation") or [{}])[-1]
    pools = preparation.get("pools", {})
    latest_decisions, parent_actions, reextractions, quality_ended = review_progress(get, jobs, events)
    lifecycle=next((e["payload"].get("lifecycle") for e in reversed(events) if e["kind"]=="task_state_changed"),None)
    task_ended=lifecycle in TERMINAL_TASKS

    def title(work_id):
        source = sources.get(work_id, {})
        records = works.get(work_id, {}).get("records", [])
        return (text(source.get("title")) or text(records[0].get("title") if records else None)
                or text(works.get(work_id, {}).get("canonical_key")) or "尚无题名")

    def work_jobs(kinds):
        return [
            {"id": jid, "kind": job["kind"], "state": job["status"],
             "work_id": job["payload"].get("work_id"), "payload": job["payload"]}
            for jid, job in jobs.items() if job["kind"] in kinds
        ]

    pool = (get("catalog_pool") or [{}])[-1]
    catalog_jobs = work_jobs({"catalog_extract"})
    table_items = []
    table_jobs = {}
    for job in catalog_jobs:
        table_jobs.setdefault(job["payload"].get("table_id",job["id"]),[]).append(job)
    for table_id, checks in table_jobs.items():
        job=checks[-1]
        payload = job["payload"]
        table_id = payload.get("table_id", job["id"])
        states={check["state"] for check in checks}
        state=("running" if "running" in states else "waiting" if states-FINISHED else
               "failed" if "failed" in states else job["state"])
        item = {"id": table_id, "label": table_id, "state": state}
        if task_ended and state not in FINISHED:
            item["display_state"]="ended_incomplete"
        source = next((s for s in sources.values() if s.get("table_id") == table_id), None)
        if source:
            item["source_id"] = source["source_id"]
        table_items.append(item)
    discovered_items=[]
    for table_id in pool.get("discovered_tables", []):
        if not any(item["id"] == table_id for item in table_items):
            discovered_items.append({"id": table_id, "label": table_id, "state": "discovered"})
    table_items=discovered_items+table_items
    # Exact absence/identity conclusions require explicit matching evidence.
    # A failed table job alone says nothing about the presence of the target.
    coverage = get("coverage")
    for item in table_items:
        outcome = next((x for x in reversed(coverage) if x.get("table_id")==item["id"]), {})
        limitation = next((x for x in reversed(coverage) if
            x.get("scope",{}).get("table_id")==item["id"] and
            x.get("reason")=="CATALOG_IDENTITY_LIMITATION_SCOPE"),None)
        item["outcome"] = ("no_verified_rows" if outcome.get("verified_row_count")==0
                           else "no_property_columns" if outcome.get("property_columns_state")=="missing"
                           else "access_incomplete" if outcome.get("access_state")=="incomplete"
                           else "identity_unresolved" if limitation else None)
        candidates = [
            c for c in get("candidate")
            if c.get("assembly_context", {}).get("source", {}).get("table_id") == item["id"]
        ]
        if candidates:
            item["candidate_count"] = len(candidates)
            item["outcome"] = "candidates"
    table_progress=job_progress([{"state":item["state"]} for item in table_items if item["id"] in table_jobs])
    catalog = {
        "availability": "available" if pool or catalog_jobs else "not_recorded",
        "resources": len(set(pool.get("discovered_resources", []))) if pool else None,
        "tables": len(set(pool.get("discovered_tables", []))) if pool else None,
        "deep_checks": table_progress, "items": recent(table_items, limit),
        "closed": pool.get("closed", False),
        "outcomes": dict(Counter(item["outcome"] for item in table_items if item.get("outcome"))),
    }

    acquired = {wid for p in pools.values() for wid in p.get("acquired", [])}
    evaluated = {wid for p in pools.values() for wid in p.get("evaluated", [])}
    eligible = {wid for p in pools.values() for wid in p.get("eligible", [])}
    attempted = {wid for p in pools.values() for wid in p.get("attempted", [])}
    paper_items = []
    for wid, work in works.items():
        property_ids = [pid for pid, p in pools.items() if wid in (
            p.get("acquired", []) + p.get("evaluated", []) + p.get("eligible", []))]
        state = ("readable" if wid in acquired else "attempted" if wid in attempted
                 else "eligible" if wid in eligible else "evaluated" if wid in evaluated else "discovered")
        if not pools and sources.get(wid,{}).get("artifact"):
            state="acquired"
        if wid in attempted and any(job["status"]=="running" and job["kind"]=="acquire_work" and
                                   job["payload"].get("work_id")==wid for job in jobs.values()):
            state="acquiring"
        if preparation.get("closed") or task_ended:
            if state=="eligible":state="backup_unused"
            elif state=="acquiring":state="attempted"
        paper_items.append({"id": wid, "label": title(wid), "state": state, "property_ids": property_ids})
    papers = {
        "availability": "available" if works else "not_recorded",
        "discovered": len(works), "evaluated": len(evaluated) if pools else None, "eligible": len(eligible) if pools else None,
        "readable": len(acquired) if pools else None, "items": recent(paper_items, limit),
    }

    attachments = get("attachment")
    attachment_jobs = work_jobs({"attachment_discover"})
    attachment_items = []
    for attachment in attachments:
        association = attachment.get("association") or {}
        parent = attachment.get("parent_work_id") or attachment.get("work_id")
        if isinstance(attachment.get("parent_work_ref"), dict):
            parent = attachment["parent_work_ref"].get("id")
        attachment_items.append({
            "id": attachment.get("attachment_id") or attachment.get("table_id") or attachment.get("source_id") or association.get("declared_filename"),
            "table_id": attachment.get("table_id"),
            "label": attachment.get("original_filename") or association.get("declared_filename") or text(attachment.get("title")),
            "parent_id": parent, "parent_title": title(parent) if parent else None,
            "state": attachment.get("state") or ("acquired" if attachment.get("artifact") else "discovered"),
        })
    for source in sources.values():
        if source.get("kind") != "official_attachment":
            continue
        parent = (source.get("parent_work_ref") or {}).get("id") or source.get("parent_work_id") or source.get("work_id")
        table_id = source.get("table_id")
        match = next((item for item in attachment_items if item["id"]==source["source_id"] or table_id and item.get("table_id")==table_id),None)
        if match:
            match["state"]="readable"
            match["source_id"]=source["source_id"]
        else:
            attachment_items.append({
                "id": source["source_id"], "label": (source.get("association") or {}).get("declared_filename") or text(source.get("title")),
                "parent_id": parent, "parent_title": title(parent) if parent else None,
                "state": "readable" if source.get("artifact") else "discovered",
            })
    attachment_view = {
        "availability": "available" if attachments or attachment_jobs else "not_recorded",
        "parents": job_progress(attachment_jobs), "files": len(attachments),
        "items": recent(attachment_items, limit),
        "reading": job_progress(work_jobs({"attachment_extract"})),
    }

    batches = {b["batch_id"]: b for b in get("reading_batch_state")}
    reading_jobs = work_jobs({"paper_batch"})
    reading_items = []
    for job in reading_jobs:
        payload = job["payload"]
        batch_id = payload.get("reading_batch_id")
        batch = batches.get(batch_id, {})
        reading_items.append({
            "id": job["id"], "batch_id": batch_id, "work_id": job["work_id"],
            "label": title(job["work_id"]), "property_ids": payload.get("property_ids", []),
            "pages": payload.get("core_pages") or batch.get("core_pages", []),
            "state": job["state"], "coverage": batch.get("coverage"),
            "display_state": "ended_incomplete" if task_ended and job["state"] not in FINISHED else job["state"],
        })
    reading = {"availability": "available" if reading_items else "not_recorded",
               **job_progress(reading_jobs), "items": recent(reading_items, limit)}

    candidates = get("candidate")
    candidate_items = []
    for candidate in candidates:
        context = candidate.get("assembly_context") or {}
        proposal = candidate.get("proposal") or {}
        evidence = candidate.get("evidence") or {}
        locator = evidence.get("locator") or {}
        work_id = (context.get("source") or {}).get("source_id") or evidence.get("source_id")
        candidate_items.append({
            "id": candidate["candidate_id"], "property_id": proposal.get("property_id"),
            "work_id": work_id, "label": title(work_id), "batch_id": context.get("batch_id"),
            "evidence_id": evidence.get("evidence_id"), "page": locator.get("page"),
            "position": "region" if locator.get("bbox") or locator.get("page_bbox")
                        else "page" if locator.get("page") else "cell" if locator.get("column")
                        else "excerpt" if evidence.get("raw_text") else "not_recorded",
            "state": candidate_state(candidate, latest_decisions, parent_actions, reextractions, quality_ended),
            "reported_state": candidate.get("state"),
        })
    candidate_view = {
        "availability": "available" if candidates else "not_recorded", "total": len(candidates),
        "by_property": dict(Counter(item["property_id"] for item in candidate_items if item["property_id"])),
        "items": recent(candidate_items, limit),
    }
    roots = get("quality_candidate_root")
    decisions = get("quality_decision")
    # A root can have multiple leaves. Keep root and leaf/decision statistics separate.
    reextract_results = {r["root_id"]: r for r in get("quality_reextraction_result")}
    reextract_items = []
    for action in get("quality_reextraction_action"):
        root = action["root_id"]
        result = reextract_results.get(root)
        reextract_items.append({
            "id": root, "property_id": action.get("property_id"),
            "parent_id": (action.get("parent_candidate_ref") or {}).get("id"),
            "state": reextractions[root]["state"],
            "reported_outcome": result.get("outcome") if result else None,
            "review_states": reextractions[root]["decisions"],
            "candidate_count": result.get("candidate_count") if result else None,
            "problem": (action.get("problem") or {}).get("instruction"),
        })
    quality = {
        "availability": "available" if roots or decisions else "not_recorded",
        "roots": len(roots), "decisions": len(decisions),
        "states": dict(Counter(d["state"] for d in latest_decisions.values())),
        "unfinished_reasons": dict(Counter(d.get("reason") or "unknown" for d in latest_decisions.values()
                                           if d["state"] == "technical_failure")),
        "reextractions": len(reextract_items), "reextraction_finished": len(reextract_results),
        "items": recent(reextract_items, limit),
    }
    conclusions = 0
    links = get("quality_candidate_link")
    for root in roots:
        own = [link for link in links if link["root_id"] == root["root_id"]]
        parents = {(link.get("parent_ref") or {}).get("id") for link in own}
        leaves = [link["candidate_ref"]["id"] for link in own if link["candidate_ref"]["id"] not in parents]
        if not leaves:
            leaves = [(root.get("initial_ref") or {}).get("id")]
        states = [latest_decisions.get(leaf, {}).get("state") for leaf in leaves]
        if states and all(state in {"supported","not_applicable","not_passed","raw_retained"} for state in states):
            conclusions += 1
        elif reextract_results.get(root["root_id"],{}).get("outcome") == "no_target_result":
            conclusions += 1
    quality["concluded_roots"] = conclusions

    records = {r["measurement_id"]: r for r in get("measurement")}
    receipts = {r.get("input_ref", {}).get("id"): r for r in get("processing_receipt")}
    normalization_changes = {r["after_ref"]["id"] for r in get("change_event")
                             if r.get("operation") == "same_quantity_representation"
                             and isinstance(r.get("after_ref"), dict)}
    processed = []
    for derived in get("derived"):
        record = records.get(derived["measurement_id"], {})
        value = derived.get("value_typed") or {}
        raw = record.get("value") or {}
        units = derived.get("coordinate_units") or {}
        receipt = receipts.get(derived["measurement_id"], {})
        ready = derived.get("main_state") == "ready"
        changed = ready and derived.get("derived_id") in normalization_changes
        state = ("changed" if changed else "unchanged" if ready else
                 "failed" if derived.get("main_state") == "failed" or receipt.get("status") == "failed"
                 else "retained")
        processed.append({
            "id": derived["measurement_id"], "property_id": (record.get("property_ref") or {}).get("id"),
            "before": raw.get("value", record.get("raw_value")), "before_unit": record.get("unit"),
            "after": value.get("value"), "after_unit": units.get("target"),
            "state": state, "reason": derived.get("reason") or (derived.get("scientific_operation") or {}).get("reason"),
            "uncertainty_state": derived.get("status"),
        })
    cleaning = {"availability": "available" if processed else "not_recorded",
                "states": dict(Counter(item["state"] for item in processed)),
                "items": recent(processed, limit)}
    references = get("reported_source_ref")
    cited = get("cited_work")
    return {
        "schema_version": "ChatActivity/1", "cursor": cursor, "limit": limit,
        "catalog": catalog, "papers": papers, "attachments": attachment_view,
        "reading": reading, "candidates": candidate_view, "quality": quality, "cleaning": cleaning,
        "references": {"relations": len(references), "works": len(cited),
                       "abstracts": sum(bool(w.get("abstract")) for w in cited)},
        "figures": {"saved": len(get("figure")), "checked_sources": len(get("figure_coverage"))},
    }
