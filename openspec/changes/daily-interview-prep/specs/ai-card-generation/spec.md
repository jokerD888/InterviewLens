## ADDED Requirements

### Requirement: AI generates cards from material text
The system SHALL invoke AI service to analyze material text and produce a set of memory cards.

#### Scenario: Successful card generation
- **WHEN** a material has its text content extracted and is pending processing
- **THEN** system sends text to AI service and receives a JSON array of cards, each with `question`, `answer`, and `importance_score` (1-5)

#### Scenario: Empty or unparseable content
- **WHEN** material text is empty or AI returns no valid cards
- **THEN** system marks material status as "failed" and returns error "无法从资料中生成有效卡片，请检查内容"

### Requirement: Importance scoring
The system SHALL assign each card an importance score based on interview frequency analysis.

#### Scenario: Card importance prioritization
- **WHEN** cards are generated from material
- **THEN** each card's `importance_score` is an integer 1-5, where 5 represents the most frequently asked interview questions

### Requirement: Card generation status tracking
The system SHALL track card generation progress per material.

#### Scenario: Material processing states
- **WHEN** material status transitions through the pipeline
- **THEN** status follows: `uploaded` → `processing` → `completed` or `failed`
