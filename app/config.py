"""Application configuration (environment variables / local ``.env`` file).

``POSTING_MODE`` selects the operating mode:

* ``demo`` (default): nothing is published and no credentials are needed.
* ``live``: real posts are created through each platform's official API.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PostingMode = Literal["demo", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Automated Multi-Platform Posting System"
    posting_mode: PostingMode

    # --- Timeouts / verification -------------------------------------------
    # Hard limit for ONE platform's whole flow (publish + public check), enforced with asyncio.
    platform_timeout_seconds: float = 30.0
    # Timeout of each individual HTTPX request.
    http_timeout_seconds: float = 15.0
    # After publishing, the post URL is fetched anonymously to verify public access.
    public_check_attempts: int = 3
    public_check_delay_seconds: float = 1.5

    # --- Bluesky (AT Protocol) ----------------------------------------------
    bluesky_handle: str = ""
    bluesky_app_password: str = ""
    bluesky_pds_url: str = "https://bsky.social"
    bluesky_public_api_url: str = "https://public.api.bsky.app"

    # --- Mastodon -----------------------------------------------------------
    mastodon_instance: str = ""  # e.g. https://mastodon.social
    mastodon_access_token: str = ""

    # --- DEV.to (Forem API) -------------------------------------------------
    devto_api_key: str = ""

    # --- Hashnode (GraphQL) -------------------------------------------------
    hashnode_api_key: str = ""
    hashnode_publication_id: str = ""
    hashnode_graphql_url: str = "https://gql.hashnode.com"

    # --- WordPress (REST API, self-hosted / Application Passwords) -----------
    wordpress_url: str = ""  # e.g. https://myblog.example.com
    wordpress_username: str = ""
    wordpress_app_password: str = ""

    @field_validator("posting_mode", mode="before")
    @classmethod
    def _normalise_mode(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
