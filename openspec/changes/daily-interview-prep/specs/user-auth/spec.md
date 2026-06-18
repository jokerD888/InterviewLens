## ADDED Requirements

### Requirement: User registration
The system SHALL allow new users to register with a unique username and password.

#### Scenario: Successful registration
- **WHEN** user submits a unique username and password (min 6 chars)
- **THEN** system creates the account and returns a JWT access token

#### Scenario: Duplicate username
- **WHEN** user submits an already-taken username
- **THEN** system returns 409 Conflict with error message "用户名已存在"

### Requirement: User login
The system SHALL authenticate registered users and issue a JWT token.

#### Scenario: Successful login
- **WHEN** user submits valid username and password
- **THEN** system returns a JWT access token with 7-day expiry

#### Scenario: Invalid credentials
- **WHEN** user submits wrong password or non-existent username
- **THEN** system returns 401 Unauthorized with error message "用户名或密码错误"

### Requirement: JWT authentication guard
The system SHALL require a valid JWT token for all protected API endpoints.

#### Scenario: Valid token
- **WHEN** request includes a valid JWT in Authorization header
- **THEN** request proceeds to the protected endpoint

#### Scenario: Missing or expired token
- **WHEN** request lacks Authorization header or token is expired
- **THEN** system returns 401 Unauthorized
