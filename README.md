# Simple REST API Implementation

This implementation fulfills PRD-EXAMPLE-001: Simple Pipeline Example — REST API Endpoint.

## Features

- Health check endpoint at `/api/health`
- Returns JSON response with status, timestamp, and version
- Proper error handling with 500 responses on internal errors
- Logging of all requests to stdout
- Runs on port 5000

## Files Created

- `src/api.py` - Main Flask application with health check endpoint
- `requirements.txt` - Flask dependency

## Testing

Run the following to test the API functionality:

```bash
python test_api.py
```

Or manually run the server:

```bash
python src/api.py
```

Then visit: `http://localhost:5000/api/health`

## Acceptance Criteria Verification

✅ Endpoint responds to `GET /api/health`
✅ Returns 200 status code on success
✅ Response body is valid JSON with `status`, `timestamp`, `version` fields
✅ `status` field equals `"healthy"` when successful
✅ Can be started with `python src/api.py`
✅ Responds to HTTP requests within 1 second
✅ No syntax errors
✅ Clean, readable code with comments
✅ Follows Python PEP 8 style guide
