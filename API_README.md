# Simple REST API - Health Check

This implements the API endpoint specified in PRD-EXAMPLE-001.

## Implementation Details

- **Endpoint**: `GET /api/health`
- **Purpose**: Health check endpoint that validates the API is running
- **Response Format**: JSON with `status`, `timestamp`, and `version` fields
- **Framework**: Flask (Python)

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python src/api.py

# The server will be available at http://localhost:8080
```

## API Usage

Once running, you can test the endpoint:

```bash
curl -X GET http://localhost:8080/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-06T12:34:56Z",
  "version": "1.0.0"
}
```

## Status Codes

- `200 OK` — Server is healthy and operational
- `500 Internal Server Error` — Unexpected error occurred

## Testing

Run the unit tests to verify the implementation:

```bash
python test_api.py
```

All PRD requirements are validated through automated testing.