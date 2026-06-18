## ADDED Requirements

### Requirement: Frontend batch-select interview questions
The InterviewLens frontend SHALL allow users to select multiple questions from search results or post detail views via checkboxes.

#### Scenario: Select questions from search results
- **WHEN** user views `/search` page with search results
- **THEN** each question card displays a checkbox
- **AND** a top toolbar shows the count of selected questions

#### Scenario: Select all and deselect all
- **WHEN** user clicks "全选" in the toolbar
- **THEN** all visible questions are checked
- **WHEN** user clicks "取消全选"
- **THEN** all checkboxes are cleared

#### Scenario: Export button state
- **WHEN** no questions are selected
- **THEN** the "加入八股" button is disabled
- **WHEN** at least one question is selected
- **THEN** the "加入八股" button is enabled and shows selected count

### Requirement: AI answer generation for selected questions
The InterviewLens backend SHALL generate reference answers for selected questions using DeepSeek API when the user initiates export.

#### Scenario: Generate answers via bridge API
- **WHEN** user clicks "加入八股" and confirms
- **THEN** frontend calls `POST /api/bridge/generate-answers` with the list of question IDs
- **AND** backend calls DeepSeek for each question to generate a complete answer
- **AND** backend returns the original question content with generated answer and estimated importance_score

#### Scenario: Handle generation timeout
- **WHEN** DeepSeek API does not respond within 60 seconds for a question
- **THEN** that question is marked as generation failed with an error message
- **AND** other questions continue generation independently

#### Scenario: Generation prompt includes context
- **WHEN** generating answer for a question
- **THEN** the prompt to DeepSeek SHALL include the question content
- **AND** if available, include company name and position as context for targeted answer

### Requirement: Answer preview and editing
The InterviewLens frontend SHALL display a preview modal showing each generated answer before final import.

#### Scenario: Preview modal opens after generation
- **WHEN** AI generation completes
- **THEN** a modal displays showing each question with its generated answer
- **AND** each answer is in an editable textarea

#### Scenario: Edit answer before import
- **WHEN** user modifies an answer in the textarea
- **THEN** the modified content is used for import, not the AI-generated original
- **WHEN** user clicks "取消"
- **THEN** the modal closes and no cards are imported

#### Scenario: Confirm import
- **WHEN** user reviews answers and clicks "确认导入"
- **THEN** frontend calls `POST /api/bridge/export` with the finalized question-answer pairs

### Requirement: Export to daily-interview-prep
The InterviewLens backend SHALL call the daily-interview-prep bulk-import API with finalized cards after user confirmation.

#### Scenario: Successful export
- **WHEN** `POST /api/bridge/export` is called with validated cards
- **THEN** backend sends `POST /api/cards/bulk-import` to daily-interview-prep with Authorization header
- **AND** returns the import result (imported count, skipped count) to the frontend

#### Scenario: Export failure handling
- **WHEN** daily-interview-prep API is unreachable
- **THEN** backend returns HTTP 502 with error message "八股服务不可达"
- **WHEN** daily-interview-prep API returns 401
- **THEN** backend returns HTTP 502 with error message "八股服务认证失败，请检查 Token 配置"

#### Scenario: Result feedback
- **WHEN** import completes (with or without partial skips)
- **THEN** frontend displays a toast: "成功导入 X 张卡片" or with skip details
