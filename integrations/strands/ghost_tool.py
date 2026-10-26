import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strands import tool

from ghostdata.agent.tools.s3_ghosts import GhostFinder
from ghostdata.observations import identifier_keys


@tool
def find_ghost_copies(bucket: str, prefix: str, identifiers: list[str]) -> dict:
    """Find copies of a person's data that survived a deletion in a versioned S3 bucket.

    Lists every object version and delete marker under the prefix, reads each version's bytes,
    and reports the versions that contain any of the identifiers. A version hidden behind a
    delete marker still holds the data: deleting the current object does not remove it.
    Read-only: nothing is deleted. The returned delete commands are proposals for a human.

    Args:
        bucket: S3 bucket name, without the s3:// scheme.
        prefix: Key prefix to search, e.g. "exports/". Narrow it on large buckets.
        identifiers: The person's emails, phone numbers and sha256 email hashes,
            current and historical.

    Returns:
        A dict with versions_scanned, delete_markers, copies (key, version_id, is_latest,
        hidden_by_delete_marker, legal_hold, matched identifiers, linked identifiers,
        Comprehend PII types) and proposed_delete_commands, which skip legal-hold versions.
    """
    keys = identifier_keys(list(identifiers))
    if not keys:
        return {"status": "error", "content": [{"text": "no email, phone or email hash found in identifiers"}]}
    finder = GhostFinder(bucket)
    found = finder.search(finder.session("strands-ghost-tool"), prefix, keys)
    result = found.for_model()
    result["proposed_delete_commands"] = [c.delete_command for c in found.copies if not c.legal_hold]
    result["kept_for_legal_hold"] = [c.uri for c in found.copies if c.legal_hold]
    return result
