"""
Simple API endpoint that returns 200 as required by PRD-EXAMPLE-001.
"""

from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Example API Endpoint", version="1.0.0")

@app.get("/")
async def root():
    """
    Root endpoint that returns a 200 status code.

    Acceptance criteria: API endpoint returns 200
    """
    return {"status": "ok", "message": "API is running"}

@app.get("/health")
async def health_check():
    """
    Health check endpoint that returns 200.
    """
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
