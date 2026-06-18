## ADDED Requirements

### Requirement: Web Push notification
The system SHALL send a daily push notification reminding users to review their cards.

#### Scenario: Push sent at configured time
- **WHEN** the configured daily push time is reached (default 9:00 AM user local time)
- **THEN** system sends a Web Push notification with title "今日八股复习" and body showing pending card count

#### Scenario: Push when no cards pending
- **WHEN** push time is reached but user has no pending cards
- **THEN** system does NOT send a push notification

### Requirement: Push subscription management
The system SHALL store Web Push subscriptions and handle unsubscription.

#### Scenario: Subscribe to push
- **WHEN** user grants notification permission and subscribes
- **THEN** system stores the subscription object (endpoint, keys) linked to the user

#### Scenario: Unsubscribe
- **WHEN** user revokes notification permission or unsubscribes
- **THEN** system removes the subscription record

### Requirement: Today's cards endpoint
The system SHALL provide an API endpoint returning the user's daily card queue.

#### Scenario: Fetch today's cards
- **WHEN** user requests GET /api/daily-cards
- **THEN** system returns a list of cards with id, question, answer (masked until flip), importance_score, and review_state
