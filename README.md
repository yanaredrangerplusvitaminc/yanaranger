# Ranger RevOps

## HubSpot <-> Monaco sync

Daily two-way sync of Yana Rova's and Sari Saadi's contacts and companies.

- HubSpot sends status (lifecycle, lead status, owner, company details) to Monaco.
- Monaco sends LinkedIn conversations to HubSpot, as one note per thread.
- Identity fields only fill blanks. Nothing is deleted.

Files:
- `sync/PLAYBOOK.md`: the run procedure and the full rule table
- `sync/planner.py`: decides every change from snapshots of both systems (no API calls)
- `sync/config.json`: owners, IDs and status mappings
- `sync/tests/`: `python3 -m unittest discover -s sync/tests`
