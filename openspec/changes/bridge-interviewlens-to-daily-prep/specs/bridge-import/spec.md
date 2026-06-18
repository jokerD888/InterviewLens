## ADDED Requirements

### Requirement: Bulk import endpoint
The daily-interview-prep backend SHALL expose a `POST /api/cards/bulk-import` endpoint that accepts an array of cards from external systems.

#### Scenario: Successful bulk import
- **WHEN** a valid JWT-authenticated request is received with `{"cards": [{"question": "...", "answer": "...", "importance_score": 4}]}`
- **THEN** each card is inserted into the `cards` table with `scheduler_state = "new"`, `review_count = 0`, `next_review_at = today`
- **AND** a corresponding `card_progress` row is created for the authenticated user
- **AND** response returns `{"imported": N, "skipped": 0, "skipped_reasons": []}`

#### Scenario: Duplicate question detection
- **WHEN** a card's question text already exists in the user's cards
- **THEN** that card is skipped (not inserted)
- **AND** the skip reason is recorded as "问题重复: '<question>'"

#### Scenario: Partial success
- **WHEN** a batch contains both new and duplicate questions
- **THEN** new questions are imported and duplicates are skipped
- **AND** response returns accurate `imported` and `skipped` counts

#### Scenario: Unauthenticated request
- **WHEN** the request does not include a valid JWT token
- **THEN** response returns HTTP 401

#### Scenario: Invalid request body
- **WHEN** `cards` array is empty or missing
- **THEN** response returns HTTP 422 with validation error
- **WHEN** any card is missing `question` field
- **THEN** response returns HTTP 422 with field-level error detail

#### Scenario: Source URL tracking
- **WHEN** a card includes an optional `source_url` field
- **THEN** the source_url is stored in the card record for reference

### Requirement: Imported cards enter learning queue
Cards imported via bulk-import SHALL be immediately available in the user's daily card queue.

#### Scenario: New card appears in daily cards
- **WHEN** a new card is imported with `scheduler_state = "new"` and `next_review_at = today`
- **THEN** it appears in `GET /api/daily-cards` results for that user
- **AND** the card is eligible for review according to existing daily quota rules (10 new + 20 review)
