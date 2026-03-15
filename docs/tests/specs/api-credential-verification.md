---
title: "Credential Verification API Endpoint"
status: active
type: reference
service: backend
port: 8000
prerequisites:
  - "Backend API running on port 8000"
  - "Eddy validation service running on port 5184"
  - "Valid API authentication configured (if applicable)"
tags: [regression, critical]
estimated_duration: "2-4 minutes"
---

# Credential Verification API Endpoint

## Description

Validates the core `/agencheck` API endpoint that processes credential verification requests. This endpoint is the backbone of the AgenCheck system -- it accepts institution and credential details, orchestrates verification through Eddy, and returns a structured response. This test sends a POST request via the browser-based API documentation interface and validates the response structure and content.

## Steps

1. **Navigate** to `http://localhost:8000/docs`
   - Expected: FastAPI Swagger UI loads with the API endpoint documentation

2. **Capture** screenshot of API documentation page
   - Target: `screenshots/01-api-docs-loaded.png`
   - Expected: Screenshot saved showing Swagger UI with available endpoints

3. **Click** the `/agencheck` POST endpoint section to expand it
   - Target: The `/agencheck` endpoint row in the Swagger UI endpoint listing
   - Expected: Endpoint details expand showing request body schema, parameters, and response format

4. **Click** the "Try it out" button for the `/agencheck` endpoint
   - Target: "Try it out" button within the expanded `/agencheck` section
   - Expected: The request body field becomes editable

5. **Fill** the request body with a credential verification payload
   - Target: Request body textarea in the Swagger UI
   - Expected: The following JSON appears in the request body field:
     ```json
     {
       "institution": "MIT",
       "credential_type": "degree",
       "details": {
         "name": "Jane Doe",
         "degree": "Bachelor of Science",
         "year": 2020
       }
     }
     ```

6. **Capture** screenshot of prepared request
   - Target: `screenshots/06-request-prepared.png`
   - Expected: Screenshot saved showing the filled-in request body before execution

7. **Click** the "Execute" button
   - Target: "Execute" button in the Swagger UI `/agencheck` section
   - Expected: Request is sent to the backend and the response section populates

8. **Wait** for the API response to appear (timeout: 30s)
   - Expected: The Swagger UI response section shows the server response with status code and body

9. **Assert** the response status code is 200
   - Expected: The response section displays HTTP status code 200 (or equivalent success code)

10. **Assert** the response body contains a structured verification result
    - Expected: Response JSON includes at minimum:
      - A `status` field (e.g., "pending", "verified", "in_progress")
      - An `institution` field matching "MIT"
      - A `request_id` or equivalent tracking identifier

11. **Capture** screenshot of successful response
    - Target: `screenshots/11-verification-response.png`
    - Expected: Screenshot saved showing the full API response

12. **Assert** the response contains no error fields at the top level
    - Expected: No `error`, `detail`, or `message` fields indicating a server-side failure

13. **Navigate** to `http://localhost:8000/docs`
    - Expected: Swagger UI reloads fresh for the error case test

14. **Click** the `/agencheck` POST endpoint section to expand it
    - Target: The `/agencheck` endpoint row in the Swagger UI
    - Expected: Endpoint details expand

15. **Click** the "Try it out" button for the `/agencheck` endpoint
    - Target: "Try it out" button within the expanded section
    - Expected: Request body field becomes editable

16. **Fill** the request body with an invalid payload (missing required fields)
    - Target: Request body textarea in the Swagger UI
    - Expected: The following incomplete JSON appears:
      ```json
      {
        "institution": ""
      }
      ```

17. **Click** the "Execute" button
    - Target: "Execute" button in the Swagger UI
    - Expected: Request is sent and response populates

18. **Wait** for the error response to appear (timeout: 15s)
    - Expected: The Swagger UI response section shows the server response

19. **Assert** the response status code indicates a client error (400 or 422)
    - Expected: Response shows HTTP 400 (Bad Request) or 422 (Unprocessable Entity)

20. **Assert** the error response contains a descriptive error message
    - Expected: Response body includes an error detail explaining what was missing or invalid

21. **Capture** screenshot of error response
    - Target: `screenshots/21-error-response.png`
    - Expected: Screenshot saved showing the validation error response

## Evidence

| Step | Screenshot | Description |
|------|-----------|-------------|
| 2 | `screenshots/01-api-docs-loaded.png` | Swagger UI with endpoint listing |
| 6 | `screenshots/06-request-prepared.png` | Request body filled with MIT verification payload |
| 11 | `screenshots/11-verification-response.png` | Successful 200 response with verification result |
| 21 | `screenshots/21-error-response.png` | 400/422 error response for invalid payload |

## Pass/Fail Criteria

- ALL Assert steps (9, 10, 12, 19, 20) must pass
- Valid credential request returns HTTP 200 with structured verification data
- Invalid credential request returns HTTP 400 or 422 with descriptive error
- Response JSON schema matches expected structure (status, institution, request_id)
- Screenshots captured for all four evidence steps
- No 500-level server errors for either valid or invalid requests
- API response times under 30 seconds for the valid request
