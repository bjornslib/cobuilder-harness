---
title: "Backend Service Health Endpoint Checks"
status: active
type: reference
service: backend
port: 8000
prerequisites:
  - "Backend API running on port 8000"
  - "Eddy validation service running on port 5184"
  - "User chat service running on port 5185"
tags: [smoke, critical]
estimated_duration: "1-2 minutes"
---

# Backend Service Health Endpoint Checks

## Description

Validates that all backend service health endpoints return HTTP 200 with appropriate response bodies. Health checks are the foundation of deployment validation -- if any service health endpoint fails, no further testing should proceed. This test covers the core backend API, the Eddy validation service, and the user chat relay service.

## Steps

1. **Navigate** to `http://localhost:8000/health`
   - Expected: Browser loads the health endpoint and displays a JSON response

2. **Assert** the backend API health response returns status 200 with a healthy indicator
   - Expected: Response body contains JSON with a health status field indicating the service is operational (e.g., `{"status": "healthy"}` or `{"status": "ok"}`)

3. **Capture** screenshot of backend health response
   - Target: `screenshots/03-backend-health.png`
   - Expected: Screenshot saved showing the JSON health response from port 8000

4. **Navigate** to `http://localhost:5184/health`
   - Expected: Browser loads the Eddy validation service health endpoint

5. **Assert** the Eddy validation health response returns status 200 with a healthy indicator
   - Expected: Response body contains JSON with a health status field indicating the service is operational

6. **Capture** screenshot of Eddy validation health response
   - Target: `screenshots/06-eddy-validate-health.png`
   - Expected: Screenshot saved showing the JSON health response from port 5184

7. **Navigate** to `http://localhost:5185/health`
   - Expected: Browser loads the user chat service health endpoint

8. **Assert** the user chat health response returns status 200 with a healthy indicator
   - Expected: Response body contains JSON with a health status field indicating the service is operational

9. **Capture** screenshot of user chat health response
   - Target: `screenshots/09-user-chat-health.png`
   - Expected: Screenshot saved showing the JSON health response from port 5185

10. **Navigate** to `http://localhost:8000/docs`
    - Expected: FastAPI auto-generated Swagger/OpenAPI documentation page loads

11. **Assert** the API documentation page renders with endpoint listings
    - Expected: Swagger UI is visible with at least the `/health` and `/agencheck` endpoints listed

12. **Capture** screenshot of API documentation page
    - Target: `screenshots/12-api-docs.png`
    - Expected: Screenshot saved showing the Swagger documentation interface

## Evidence

| Step | Screenshot | Description |
|------|-----------|-------------|
| 3 | `screenshots/03-backend-health.png` | Backend API (port 8000) health response |
| 6 | `screenshots/06-eddy-validate-health.png` | Eddy validation service (port 5184) health response |
| 9 | `screenshots/09-user-chat-health.png` | User chat service (port 5185) health response |
| 12 | `screenshots/12-api-docs.png` | FastAPI Swagger documentation renders correctly |

## Pass/Fail Criteria

- ALL Assert steps (2, 5, 8, 11) must pass
- All three health endpoints return HTTP 200 status codes
- All health responses contain valid JSON with a status indicator
- API documentation page loads and displays endpoint listings
- Screenshots captured for all four evidence steps
- No connection refused or timeout errors on any endpoint
