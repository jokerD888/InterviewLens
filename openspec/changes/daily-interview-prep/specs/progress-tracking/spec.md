## ADDED Requirements

### Requirement: Daily streak tracking
The system SHALL track consecutive days the user has reviewed cards.

#### Scenario: Streak increases
- **WHEN** user reviews at least one card today and yesterday was also a review day
- **THEN** user's streak counter increments by 1

#### Scenario: Streak breaks
- **WHEN** user has 0 reviews on a calendar day
- **THEN** user's streak resets to 0 the next time they review

### Requirement: Card mastery statistics
The system SHALL provide summary statistics on card learning progress.

#### Scenario: Progress summary
- **WHEN** user requests GET /api/progress
- **THEN** system returns: total_cards, mastered_count, learning_count (level_0~5), new_count, daily_streak, today_reviewed, today_remaining

### Requirement: Review history timeline
The system SHALL allow users to view their review history by date.

#### Scenario: View review calendar
- **WHEN** user requests GET /api/progress/history?month=2026-06
- **THEN** system returns an array of dates with review_count for each day in the month
