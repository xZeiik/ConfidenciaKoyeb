import json, os
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from .models import GoogleCalendarCredential

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def build_flow():
    return Flow.from_client_secrets_file(
        settings.GOOGLE_CALENDAR_CREDENTIALS,
        scopes=settings.GOOGLE_CALENDAR_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )

def save_user_credentials(user, creds: Credentials):
    data = json.loads(creds.to_json())
    obj, _ = GoogleCalendarCredential.objects.update_or_create(
        user=user,
        defaults={"credentials_json": json.dumps(data)},
    )
    return obj

def load_user_credentials(user) -> Credentials | None:
    try:
        stored = user.gcal.credentials_json
    except GoogleCalendarCredential.DoesNotExist:
        return None
    info = json.loads(stored)
    creds = Credentials.from_authorized_user_info(info, settings.GOOGLE_CALENDAR_SCOPES)
    # Refrescar si expiró y hay refresh_token
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_user_credentials(user, creds)
    return creds

def get_calendar_service(user):
    creds = load_user_credentials(user)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)
