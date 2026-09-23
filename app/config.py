import os
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
OPINET_API_KEY = os.getenv("OPINET_API_KEY", "")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
EVIDENCE_BUCKET = os.getenv("EVIDENCE_BUCKET", "")

ACCESS_CONTROL_ENABLED = os.getenv("ACCESS_CONTROL_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
OWNER_ACCESS_KEY = os.getenv("OWNER_ACCESS_KEY", "")
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "ddalkkak_access")
ACCESS_ENTRY_MODE = os.getenv("ACCESS_ENTRY_MODE", "link").strip().lower()
