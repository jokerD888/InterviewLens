## ADDED Requirements

### Requirement: Card state progression
Each card SHALL follow the Ebbinghaus interval sequence: new → 1d → 2d → 4d → 7d → 15d → 30d → mastered.

#### Scenario: Correct recall advances card
- **WHEN** user marks a review card as "记住了"
- **THEN** card's level advances one step and next_review_at is set to current_time + interval

#### Scenario: Forgotten recall resets card
- **WHEN** user marks a review card as "忘了"
- **THEN** card's level resets to level_0 (1-day interval) and next_review_at is set to tomorrow

### Requirement: Daily review quota
The system SHALL compute a daily review quota consisting of due review cards first, then new cards up to the configured limit.

#### Scenario: Fetch daily cards with more reviews than quota
- **WHEN** user requests today's cards and due_reviews > daily_review_limit
- **THEN** system returns the oldest due review cards up to daily_review_limit, with zero new cards

#### Scenario: Fetch daily cards with room for new cards
- **WHEN** user requests today's cards and due_reviews < daily_total_quota
- **THEN** system returns all due reviews plus new cards (prioritized by importance_score desc) filling up to daily_total_quota

### Requirement: Card assignment to user
The system SHALL assign each new card to a specific user upon first review.

#### Scenario: New card assigned on first retrieval
- **WHEN** user fetches new cards for the first time
- **THEN** system creates CardProgress records linking user and card, with state = "new"

### Requirement: Review history record
The system SHALL log every review attempt with result and timestamp.

#### Scenario: Review logged after self-assessment
- **WHEN** user submits a review result (记住了/忘了) for a card
- **THEN** system records the review with user_id, card_id, result, and timestamp
