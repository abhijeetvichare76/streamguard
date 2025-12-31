"""Centralized GCP credential management for Google ADK agents.

This module handles credential setup for Vertex AI and cleans up temporary files
to prevent security issues.
"""
import os
import tempfile
import json
import atexit
from typing import Optional, Tuple

# Track temp files for cleanup
_temp_files = []

def _cleanup_temp_files():
    """Clean up all temporary credential files on exit."""
    for temp_file_path in _temp_files:
        try:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        except Exception as e:
            print(f"Warning: Failed to clean up temp file {temp_file_path}: {e}")

# Register cleanup on exit
atexit.register(_cleanup_temp_files)


def setup_gcp_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Set up GCP credentials via environment variables for Google ADK.

    ADK reads credentials from environment variables:
    - GOOGLE_GENAI_USE_VERTEXAI: Set to TRUE for Vertex AI
    - GOOGLE_CLOUD_PROJECT: GCP project ID
    - GOOGLE_CLOUD_LOCATION: Vertex AI region
    - GOOGLE_APPLICATION_CREDENTIALS: Path to service account JSON file

    Returns:
        Tuple of (project_id, region) for reference

    Raises:
        ValueError: If credentials cannot be loaded from any source
    """
    project_id = None
    region = None

    # Try Streamlit secrets first
    try:
        import streamlit as st
        if hasattr(st, 'secrets'):
            # Set up Vertex AI mode via environment variable
            os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'TRUE'

            # Get project ID from secrets or service account
            project_id = st.secrets.get("GCP_PROJECT_ID")
            if not project_id and "gcp_service_account" in st.secrets:
                project_id = st.secrets["gcp_service_account"].get("project_id")

            # Set project ID environment variable
            if project_id:
                os.environ['GOOGLE_CLOUD_PROJECT'] = project_id

            # Get and set region
            region = st.secrets.get("GCP_REGION", "us-central1")
            os.environ['GOOGLE_CLOUD_LOCATION'] = region

            # Set up service account credentials file
            if "gcp_service_account" in st.secrets:
                service_account_info = dict(st.secrets["gcp_service_account"])

                # Create a temporary file for the service account key
                temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
                json.dump(service_account_info, temp_file)
                temp_file.close()

                # Track for cleanup
                _temp_files.append(temp_file.name)

                # Set the environment variable
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_file.name

            return project_id, region
    except (ImportError, Exception) as e:
        # Streamlit not available or secrets not configured
        pass

    # Fall back to environment variables
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_REGION", "us-central1")

    # If we have env vars, set them in the expected format
    if project_id:
        os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'TRUE'
        os.environ['GOOGLE_CLOUD_PROJECT'] = project_id
        os.environ['GOOGLE_CLOUD_LOCATION'] = region

        # Check if GOOGLE_APPLICATION_CREDENTIALS is already set
        if not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
            # Try to find service account key file in project root
            possible_paths = [
                'gcloud-service-account-key.json',
                'service-account-key.json',
                '.gcp/service-account-key.json'
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.path.abspath(path)
                    break

    if not project_id or not region:
        raise ValueError(
            "GCP credentials not found. Please set GCP_PROJECT_ID and GCP_REGION "
            "environment variables or configure Streamlit secrets."
        )

    return project_id, region


def get_project_id() -> str:
    """Get the configured GCP project ID.

    Returns:
        The GCP project ID

    Raises:
        ValueError: If project ID is not configured
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise ValueError("GCP project ID not configured")
    return project_id


def get_region() -> str:
    """Get the configured GCP region.

    Returns:
        The GCP region (defaults to us-central1)
    """
    return os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_REGION", "us-central1")
