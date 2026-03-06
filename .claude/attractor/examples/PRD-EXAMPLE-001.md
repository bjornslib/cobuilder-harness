# PRD-EXAMPLE-001: Simple Pipeline Example — REST API Endpoint

## Overview

Implement a basic REST API endpoint as a demonstration of the Attractor pipeline's ability to orchestrate code generation from requirements to working implementation.

## Business Requirement

Create a minimal HTTP server with a single endpoint that processes data and returns a successful response. This serves as proof that the pipeline can:
1. Parse requirements from a PRD
2. Generate implementation code
3. Validate acceptance criteria
4. Transition through pipeline stages

## Technical Specification

### Endpoint: `GET /api/health`

**Purpose**: Health check endpoint that validates the API is running.

**Request**:
```
GET /api/health
Content-Type: application/json
```

**Response (200 OK)**:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-06T12:34:56Z",
  "version": "1.0.0"
}
```

**Status Codes**:
- `200 OK` — Server is healthy and operational
- `500 Internal Server Error` — Unexpected error occurred

### Implementation Requirements

1. **Framework**: Use Python with Flask or FastAPI (your choice based on simplicity)
2. **Location**: Create `src/api.py` with the health check endpoint
3. **Port**: Listen on `http://localhost:5000`
4. **Error Handling**: Return proper JSON error responses with descriptive messages
5. **Logging**: Log all requests to stdout with timestamp and endpoint

### Code Quality Acceptance Criteria

1. **Functionality**:
   - [ ] Endpoint responds to `GET /api/health`
   - [ ] Returns 200 status code on success
   - [ ] Response body is valid JSON with `status`, `timestamp`, `version` fields
   - [ ] `status` field equals `"healthy"` when successful

2. **Testing**:
   - [ ] Can be started with `python src/api.py`
   - [ ] Responds to HTTP requests within 1 second
   - [ ] Curl test passes: `curl http://localhost:5000/api/health`

3. **Code Standards**:
   - [ ] No syntax errors
   - [ ] Clean, readable code with comments for non-obvious logic
   - [ ] Follows Python PEP 8 style guide

## Success Criteria

The implementation is complete when:
- ✅ API endpoint returns HTTP 200
- ✅ Response JSON is properly formatted
- ✅ Can be started and responds to requests
- ✅ All acceptance criteria in the "Code Quality" section are met

## Notes

- This is an intentionally simple example to validate pipeline orchestration
- Focus on getting the endpoint working correctly rather than building a full application
- The endpoint should be production-ready (proper error handling, logging, etc.)
