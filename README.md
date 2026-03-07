# feedbin-cli skill

Terminal-friendly OpenClaw skill for deterministic Feedbin workflows.

## Overview

`feedbin-cli` wraps Feedbin API operations so agents can reliably triage feeds and entries without browser automation.

## Features

- List and filter Feedbin entries, subscriptions, tags, and saved searches
- Mark entries read/unread and star/unstar in bulk or by ID
- Manage subscriptions and tagging metadata
- Save URLs as Feedbin pages
- Prefer structured CLI/API output for predictable automation

## Quick start

1. Install this skill in your OpenClaw skills directory.
2. Configure Feedbin credentials/token for the `feedbin` CLI/tooling used by your environment.
3. In OpenClaw, invoke tasks that match this skill (Feedbin triage, subscription admin, tag cleanup).
4. For full command guidance and constraints, read [`SKILL.md`](./SKILL.md).

## Safety notes

- This skill can mutate account state (read/unread, stars, subscriptions, tags).
- Prefer dry-run/read-only checks before bulk updates.
- Confirm account/context before destructive operations (unsubscribe, mass state changes).

## Documentation

- Primary instructions: [`SKILL.md`](./SKILL.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)
- Version: [`VERSION`](./VERSION)
