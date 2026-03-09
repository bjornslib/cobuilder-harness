#!/usr/bin/env python3
"""
Simple REST API Endpoint - Health Check

Implements GET /api/health endpoint as specified in PRD-EXAMPLE-001.
"""
import json
import sys
from datetime import datetime
from flask import Flask, jsonify, request
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)

# Application version
APP_VERSION = "1.0.0"

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint that validates the API is running.

    Returns:
        JSON response with status, timestamp, and version information
    """
    try:
        # Log the incoming request
        logging.info(f"Health check requested from {request.remote_addr}")

        # Prepare the response
        response_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            "version": APP_VERSION
        }

        # Log successful response
        logging.info("Health check responded with 200 OK")

        return jsonify(response_data), 200

    except Exception as e:
        # Log the error
        logging.error(f"Health check error: {str(e)}")

        # Return error response
        error_response = {
            "status": "error",
            "error": "Internal Server Error",
            "message": str(e)
        }

        return jsonify(error_response), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    logging.warning(f"Not found: {request.url}")
    return jsonify({
        "status": "error",
        "error": "Not Found",
        "message": "The requested endpoint was not found"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logging.error(f"Internal server error: {str(error)}")
    return jsonify({
        "status": "error",
        "error": "Internal Server Error",
        "message": "An internal server error occurred"
    }), 500

if __name__ == '__main__':
    print("Starting API server on http://localhost:8080...")
    print("Health endpoint: GET /api/health")
    app.run(host='localhost', port=8080, debug=False)