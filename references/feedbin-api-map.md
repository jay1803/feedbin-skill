# Feedbin API Map for `feedbin_cli.py`

## Base and auth

- Base URL: `https://api.feedbin.com/v2`
- Auth: HTTP Basic (`FEEDBIN_EMAIL` + `FEEDBIN_PASSWORD`)
- Content type for writes: `application/json; charset=utf-8`

## Command to endpoint matrix

| CLI command | Method | Endpoint | Request payload key(s) | Notes |
| --- | --- | --- | --- | --- |
| `auth check` | GET | `/authentication.json` | none | `200` valid, `401` invalid credentials |
| `entries list` | GET | `/entries.json` or `/feeds/{feed_id}/entries.json` | query params | Supports `ids/read/starred/since/page/per_page/mode` and include flags |
| `entries get <id>` | GET | `/entries/{id}.json` | query params | Supports `mode` and include flags |
| `entries mark-read` | DELETE | `/unread_entries.json` | `unread_entries` | Mark listed IDs as read |
| `entries mark-unread` | POST | `/unread_entries.json` | `unread_entries` | Mark listed IDs as unread |
| `entries star` | POST | `/starred_entries.json` | `starred_entries` | Star listed IDs |
| `entries unstar` | DELETE | `/starred_entries.json` | `starred_entries` | Unstar listed IDs |
| `subscriptions list` | GET | `/subscriptions.json` | query params | Supports `since` and `mode=extended` |
| `subscriptions get <id>` | GET | `/subscriptions/{id}.json` | none | Returns one subscription |
| `subscriptions add` | POST | `/subscriptions.json` | `feed_url` | `feed_url` can be feed URL or site URL |
| `subscriptions rename` | PATCH | `/subscriptions/{id}.json` | `title` | Alternative: POST `/subscriptions/{id}/update.json` |
| `subscriptions remove` | DELETE | `/subscriptions/{id}.json` | none | Deletes subscription |
| `pages save` | POST | `/pages.json` | `url`, `title` optional | Creates a Feedbin page entry |
| `pages remove <id>` | DELETE | `/pages/{id}.json` | none | Deletes saved page |
| `taggings list` | GET | `/taggings.json` | none | Returns all taggings |
| `taggings get <id>` | GET | `/taggings/{id}.json` | none | Returns one tagging |
| `taggings add` | POST | `/taggings.json` | `feed_id`, `name` | Creates tagging |
| `taggings remove <id>` | DELETE | `/taggings/{id}.json` | none | Deletes tagging |
| `tags rename` | POST | `/tags.json` | `old_name`, `new_name` | Renames a tag across taggings |
| `tags delete` | DELETE | `/tags.json` | `name` | Deletes tag across taggings |
| `saved-searches list` | GET | `/saved_searches.json` | none | Returns saved searches |
| `saved-searches get <id>` | GET | `/saved_searches/{id}.json` | query params | By default returns entry ID array; `include_entries=true` returns full entries |
| `saved-searches add` | POST | `/saved_searches.json` | `name`, `query` | Creates saved search |
| `saved-searches update` | PATCH | `/saved_searches/{id}.json` | `name`, `query` | Alternative: POST `/saved_searches/{id}/update.json` |
| `saved-searches remove <id>` | DELETE | `/saved_searches/{id}.json` | none | Deletes saved search |

## Entry selector behavior in mutation commands

Mutation commands resolve IDs from exactly one source:

1. `--ids <comma-separated-ids>`
2. Query filters (`--feed-id`, `--read`, `--starred`, `--since`, `--page`, `--per-page`, `--limit`) via entries API lookup

Rules:

- Do not combine `--ids` with filters.
- Mutation requests enforce a max of 1,000 IDs.
- `entries list --ids` enforces a max of 100 IDs (Feedbin API limit).

## Status and error handling notes

- Typical success codes:
  - `200 OK`: reads and most mutations
  - `201 Created`: creation endpoints
  - `204 No Content`: deletion endpoints
- Common failures:
  - `401 Unauthorized`: bad credentials
  - `403 Forbidden`: user lacks access to resource
  - `404 Not Found`: resource/feed not found
  - `300 Multiple Choices`: subscription add discovered multiple feeds
- The CLI returns non-zero exit on HTTP or transport errors and includes server response text when available.
