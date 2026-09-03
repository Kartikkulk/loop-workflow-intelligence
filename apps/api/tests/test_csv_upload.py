"""A CSV a person exported by hand has to work, not just one Kriyā AI wrote.

The console tells people it "maps common column names for you". These tests are
that claim: a spreadsheet with `Timestamp`, `Role` and `Duration` of "3 min"
has to become events, because the alternative is a file that visibly contains
the data being rejected row by row for "missing user_id".
"""

from __future__ import annotations

import pytest

from app.services.clustering import cluster_instances
from app.services.normaliser import (
    NormalisationError,
    canonical_key,
    normalise_row,
    normalise_upload,
    parse_duration_ms,
    split_action,
)
from app.services.sessioniser import sessionise

# Exactly the shape of a hand-kept enterprise activity log: capitalised
# headings, a job title instead of a user id, and durations written in words.
HAND_WRITTEN_CSV = (
    "Timestamp,Department,Role,Process,Activity,Application,Context,Record_ID,Duration\n"
    "2026-08-24 09:12,Finance,Finance Analyst,AP,Open invoice email,Email,Received,INV-1,3 min\n"
    "2026-08-24 09:18,Finance,Finance Analyst,AP,Download invoice,Gmail,INV-1,inv.pdf,2 min\n"
    "2026-08-24 09:22,Finance,Finance Analyst,AP,Enter invoice details,ERP,INV-1,Vendor,5 min\n"
    "2026-08-24 09:38,Finance,Finance Analyst,AP,Send approval email,Gmail,INV-1,Sent,2 min\n"
)


def test_the_whole_hand_written_file_parses():
    events, errors = normalise_upload("activity.csv", HAND_WRITTEN_CSV)
    assert errors == [], f"a readable CSV must not be rejected: {errors}"
    assert len(events) == 4


def test_capitalised_headings_are_the_same_column():
    assert canonical_key("Record_ID") == "record_id"
    assert canonical_key("  Record ID ") == "record_id"
    assert canonical_key("RecordID") == "recordid"
    assert canonical_key("Timestamp") == "timestamp"


def test_a_job_title_stands_in_for_a_missing_user_column():
    """No per-person id is a real limitation, but not a reason to reject."""
    events, _ = normalise_upload("activity.csv", HAND_WRITTEN_CSV)
    assert events[0].user_id == "Finance Analyst"
    assert events[0].team == "Finance"


def test_an_explicit_user_column_beats_a_role_column():
    """Order matters: a file with both must be read the precise way."""
    event = normalise_row(
        {
            "user_id": "u_asha",
            "role": "Finance Analyst",
            "timestamp": "2026-08-24 09:12",
            "application": "Gmail",
            "activity": "Open invoice email",
        }
    )
    assert event.user_id == "u_asha"


def test_a_row_with_no_person_at_all_is_still_refused():
    """Leniency has a floor: an event nobody performed cannot be attributed."""
    with pytest.raises(NormalisationError, match="user_id"):
        normalise_row({"timestamp": "2026-08-24 09:12", "application": "Gmail"})


@pytest.mark.parametrize(
    ("written", "expected_ms"),
    [
        ("3 min", 180_000),
        ("45s", 45_000),
        ("2 hours", 7_200_000),
        ("1.5 min", 90_000),
        ("90", 90_000),          # bare number in a `duration` column is seconds
        ("", 0),
        ("not a duration", 0),   # never raises: it would cost the whole row
    ],
)
def test_durations_written_the_way_people_write_them(written, expected_ms):
    assert parse_duration_ms(written) == expected_ms


def test_a_duration_ms_column_keeps_its_own_unit():
    assert normalise_row(
        {"user_id": "u", "timestamp": "2026-08-24 09:12", "app": "gmail",
         "action": "read_email", "duration_ms": 2500}
    ).duration_ms == 2500


def test_human_verbs_split_into_a_verb_and_an_object():
    """`review_resume` fused together is the token that stops clustering."""
    assert split_action("Review resume") == ("read", "resume")
    assert split_action("Approve invoice") == ("update", "invoice")
    assert split_action("Escalate to manager")[0] == "send"


def test_unclaimed_columns_survive_into_the_payload():
    """Extra columns are what drift detection later compares against."""
    events, _ = normalise_upload("activity.csv", HAND_WRITTEN_CSV)
    assert events[0].payload.get("context") == "Received"


def test_the_file_clusters_end_to_end():
    """The point of all of it: a hand-written log produces a workflow."""
    repeated = HAND_WRITTEN_CSV
    header, *rows = HAND_WRITTEN_CSV.strip().splitlines()
    for day in (25, 26, 27):
        repeated += "\n".join(r.replace("08-24", f"08-{day}") for r in rows) + "\n"

    events, errors = normalise_upload("activity.csv", repeated)
    assert errors == []
    groups = cluster_instances(sessionise(events))
    assert groups, "four repetitions of one process must cluster"
    assert max(g.size for g in groups) >= 4
