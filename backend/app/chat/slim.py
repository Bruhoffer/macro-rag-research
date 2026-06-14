"""Slim tool results for the LLM context.

The same tool result is sent to two places: the SSE stream (frontend — must stay
full, renders citation chips + linked items) and Claude's conversation history
(re-sent on every tool-loop round — this is what's billed). These helpers return a
lighter copy for the history only; the UI copy is untouched.

Pure functions — they build new dicts and never mutate the input.
"""

from typing import Any

# Fields kept from a related key-point inside a search_emails result.
_RELATED_KP_KEEP = ("key_point_id", "key_point_text", "effective_source_org")


def slim_for_llm(name: str, result: Any) -> Any:
    if not isinstance(result, list):
        return result

    if name == "get_topic_summary":
        # label_map_enriched (~36k chars/item) is built for the frontend; Claude
        # only needs label_map (label → key_point_id) for citations.
        return [{k: v for k, v in s.items() if k != "label_map_enriched"} for s in result]

    if name == "search_emails":
        return [_slim_email(e) for e in result]

    if name == "search_key_points":
        # key_point_context is the fattest field (~484 chars) and isn't needed to
        # answer or cite (key_point_text + key_point_citation carry the substance).
        return [{k: v for k, v in r.items() if k != "key_point_context"} for r in result]

    return result


def _slim_email(email: dict) -> dict:
    out = {k: v for k, v in email.items() if k != "related_key_points"}
    out["related_key_points"] = [
        {k: kp[k] for k in _RELATED_KP_KEEP if k in kp}
        for kp in email.get("related_key_points", [])
    ]
    return out
