"""BigQuery-based tools for user context retrieval."""
import os
from google.cloud import bigquery
from google.oauth2 import service_account
from google.adk.tools import FunctionTool
from dotenv import load_dotenv
from .bigquery_utils import retry_query_with_backoff

# Load environment variables
load_dotenv()

# Initialize client lazily to avoid errors if credentials are missing during import
def get_client():
    """
    Get a BigQuery client using the same credential system as data insertion.
    Tries Streamlit secrets first, then environment variables, then default credentials.
    """
    # Try Streamlit secrets first (for deployed app)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and "gcp_service_account" in st.secrets:
            credentials = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"])
            )
            project_id = st.secrets.get("GCP_PROJECT_ID", "partner-catalyst")
            return bigquery.Client(credentials=credentials, project=project_id)
    except (ImportError, Exception):
        pass

    # Try environment variable for service account key file
    key_path = os.getenv("GCP_SERVICE_ACCOUNT_KEY") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and os.path.exists(key_path):
        try:
            credentials = service_account.Credentials.from_service_account_file(key_path)
            return bigquery.Client(credentials=credentials)
        except Exception:
            pass

    # Fall back to default credentials (ADC)
    return bigquery.Client()

def get_user_history(user_id: str) -> dict:
    """
    Query BigQuery for user's profile and risk segments.

    Args:
        user_id: The user identifier to look up

    Returns:
        dict with user's profile (age, tenure, normal usage)
    """
    # Simulation fallback for test users
    if user_id == "user_good_history":
         return {"user_id": user_id, "age_group": "Active", "account_tenure_days": 3650, "avg_transfer_amount": 120.5, "behavioral_segment": "Conservative Saver"}
    if user_id == "user_senior":
         return {"user_id": user_id, "age_group": "Senior", "account_tenure_days": 5000, "avg_transfer_amount": 500.0, "behavioral_segment": "Vulnerable"}

    try:
        client = get_client()
        # Dataset: streamguard_threats, Table: customer_profiles
        dataset_id = "streamguard_threats"
        table_id = "customer_profiles"

        query = f"""
        SELECT
            user_id,
            age_group,
            account_tenure_days,
            avg_transfer_amount,
            behavioral_segment
        FROM `{dataset_id}.{table_id}`
        WHERE user_id = @user_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id)
            ]
        )

        def execute_query():
            results = client.query(query, job_config=job_config).result()
            row = next(iter(results), None)
            return row

        # Retry with exponential backoff to handle data latency
        row = retry_query_with_backoff(execute_query, max_retries=3, initial_delay=2)

        if not row:
            print(f"[BQ] User {user_id} not found after retries")
            return {"user_id": user_id, "status": "not_found", "risk": "unknown"}

        return {
            "user_id": user_id,
            "age_group": row.age_group,
            "account_tenure_days": row.account_tenure_days,
            "avg_transfer_amount": float(row.avg_transfer_amount) if row.avg_transfer_amount else 0.0,
            "behavioral_segment": row.behavioral_segment
        }
    except Exception as e:
        print(f"[BQ SIM] Fallback due to error: {e}")
        return {"user_id": user_id, "status": "simulated_error", "risk": "medium"}


def get_beneficiary_risk(account_id: str) -> dict:
    """
    Check if a beneficiary account is associated with known fraud in the graph.

    Args:
        account_id: The destination account to check

    Returns:
        dict with account age, risk score, and linked fraud indicators
    """
    # Simulation fallbacks
    if account_id == "acc_normal":
        return {"account_id": account_id, "account_age_hours": 8760, "risk_score": 10, "linked_to_flagged_device": False}
    if account_id == "acc_mule":
        return {"account_id": account_id, "account_age_hours": 12, "risk_score": 95, "linked_to_flagged_device": True}

    try:
        client = get_client()
        # Dataset: streamguard_threats, Table: beneficiary_graph
        dataset_id = "streamguard_threats"
        table_id = "beneficiary_graph"

        query = f"""
        SELECT
            account_id,
            account_age_hours,
            risk_score,
            linked_to_flagged_device
        FROM `{dataset_id}.{table_id}`
        WHERE account_id = @account_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
            ]
        )

        def execute_query():
            results = client.query(query, job_config=job_config).result()
            row = next(iter(results), None)
            return row

        # Retry with exponential backoff to handle data latency
        row = retry_query_with_backoff(execute_query, max_retries=3, initial_delay=2)

        if not row:
            # Default to high risk for unknown new accounts in this strict context
            print(f"[BQ] Beneficiary account {account_id} not found after retries")
            return {"account_id": account_id, "status": "unknown_account", "risk_score": 50}

        return {
            "account_id": account_id,
            "account_age_hours": row.account_age_hours,
            "risk_score": row.risk_score,
            "linked_to_flagged_device": row.linked_to_flagged_device
        }
    except Exception as e:
        print(f"[BQ SIM] Fallback due to error: {e}")
        return {"account_id": account_id, "status": "simulated_error", "risk_score": -1}

# Export as ADK tools
user_history_tool = FunctionTool(get_user_history)
beneficiary_tool = FunctionTool(get_beneficiary_risk)
