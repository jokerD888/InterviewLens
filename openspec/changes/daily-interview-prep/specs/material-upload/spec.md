## ADDED Requirements

### Requirement: Upload PDF material
The system SHALL accept PDF file uploads and extract readable text content.

#### Scenario: Successful PDF upload
- **WHEN** user uploads a valid PDF file (max 20MB)
- **THEN** system extracts text, stores it as a Material record, and returns material ID and title

#### Scenario: Invalid file type
- **WHEN** user uploads a non-PDF file
- **THEN** system returns 400 Bad Request with error "仅支持PDF和Markdown格式"

#### Scenario: Oversized file
- **WHEN** user uploads a file exceeding 20MB
- **THEN** system returns 413 Payload Too Large

### Requirement: Upload Markdown material
The system SHALL accept Markdown file uploads and store the raw text.

#### Scenario: Successful Markdown upload
- **WHEN** user uploads a .md file (max 20MB)
- **THEN** system stores raw markdown content as a Material record and returns material ID and title

### Requirement: List uploaded materials
The system SHALL allow users to view their uploaded materials with metadata.

#### Scenario: List materials
- **WHEN** user requests GET /api/materials
- **THEN** system returns a list of materials with id, title, upload_time, card_count, and processing_status

### Requirement: Delete material
The system SHALL allow users to delete their uploaded materials and all associated cards.

#### Scenario: Delete material with cards
- **WHEN** user deletes a material by ID
- **THEN** system deletes the material record and all cards generated from it, returns 204 No Content
