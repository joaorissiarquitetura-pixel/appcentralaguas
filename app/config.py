import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

INSECURE_SECRET_VALUES = {
    "",
    "change-me",
    "changeme",
    "secret",
    "default",
    "trocar-em-producao",
    "troque-esta-chave",
}

INSECURE_SEED_PASSWORDS = {
    "",
    "admin",
    "admin123",
    "123456",
    "password",
}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(slots=True)
class Settings:
    BUSINESS_NAME: str
    DATABASE_URL: str
    SECRET_KEY: str
    BUSINESS_WHATSAPP_NUMBER: str
    LOCAL_TZ: str
    CARD_TARGET_POINTS: int
    DOUBLE_POINTS_WEEKDAY: int
    REFERRAL_BONUS_POINTS: int
    AUTO_CREATE_TABLES: bool
    SEED_ADMIN_EMAIL: str
    SEED_ADMIN_PASSWORD: str
    SEED_ADMIN_NAME: str
    ENABLE_UNIFIED_SITE: bool
    ENABLE_SUBSCRIPTION_BRIDGE: bool
    ENABLE_COMMERCIAL_MAP: bool
    ENABLE_SIGNATURE_BANNERS: bool
    CENTRAL_AGUAS_PRODUCTS_API_URL: str
    CENTRAL_AGUAS_APP_TOKEN: str
    GRJ_CATALOG_ENABLED: bool
    GRJ_FIREBIRD_HOST: str
    GRJ_FIREBIRD_PORT: int
    GRJ_FIREBIRD_DATABASE: str
    GRJ_FIREBIRD_USER: str
    GRJ_FIREBIRD_PASSWORD: str
    GRJ_FIREBIRD_CHARSET: str
    GRJ_PRODUCTS_QUERY: str
    APP_ENV: str
    DEBUG: bool
    SESSION_COOKIE_SAME_SITE: str
    SESSION_COOKIE_SECURE: bool
    SESSION_MAX_AGE_SECONDS: int
    RESET_TOKEN_TTL_MINUTES: int
    ALLOW_AUTO_SEED_IN_PRODUCTION: bool

    @property
    def is_production(self) -> bool:
        return self.APP_ENV in {"prod", "production"}

    @property
    def insecure_secret_key(self) -> bool:
        normalized = (self.SECRET_KEY or "").strip().lower()
        return normalized in INSECURE_SECRET_VALUES or len(self.SECRET_KEY or "") < 32

    @property
    def predictable_seed_credentials(self) -> bool:
        return (
            self.SEED_ADMIN_EMAIL.strip().lower() == "admin@centralaguas.com"
            and self.SEED_ADMIN_PASSWORD.strip().lower() in INSECURE_SEED_PASSWORDS
        )

    def validate_runtime(self) -> None:
        if not self.is_production:
            return

        if self.insecure_secret_key:
            raise RuntimeError(
                "SECRET_KEY insegura em producao. Configure uma chave forte com pelo menos 32 caracteres."
            )

        if self.predictable_seed_credentials:
            raise RuntimeError(
                "Credenciais seed previsiveis nao sao permitidas em producao."
            )

        if self.AUTO_CREATE_TABLES:
            raise RuntimeError(
                "AUTO_CREATE_TABLES deve permanecer desativado em producao."
            )

        if not self.SESSION_COOKIE_SECURE:
            raise RuntimeError(
                "SESSION_COOKIE_SECURE precisa estar ativo em producao."
            )


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    debug = env_bool("DEBUG", app_env not in {"prod", "production"})
    session_cookie_secure = env_bool("SESSION_COOKIE_SECURE", app_env in {"prod", "production"})
    session_same_site = os.getenv(
        "SESSION_COOKIE_SAME_SITE",
        "strict" if app_env in {"prod", "production"} else "lax",
    ).strip().lower()

    return Settings(
        BUSINESS_NAME=os.getenv("BUSINESS_NAME", "Central Aguas - Fidelidade"),
        DATABASE_URL=os.getenv("DATABASE_URL", "sqlite:///./dev.db"),
        SECRET_KEY=os.getenv("SECRET_KEY", "change-me"),
        BUSINESS_WHATSAPP_NUMBER=os.getenv("BUSINESS_WHATSAPP_NUMBER", "55XXXXXXXXXXX"),
        LOCAL_TZ=os.getenv("LOCAL_TZ", "America/Sao_Paulo"),
        CARD_TARGET_POINTS=int(os.getenv("CARD_TARGET_POINTS", "10")),
        DOUBLE_POINTS_WEEKDAY=int(os.getenv("DOUBLE_POINTS_WEEKDAY", "2")),
        REFERRAL_BONUS_POINTS=int(os.getenv("REFERRAL_BONUS_POINTS", "2")),
        AUTO_CREATE_TABLES=env_bool("AUTO_CREATE_TABLES", app_env not in {"prod", "production"}),
        SEED_ADMIN_EMAIL=os.getenv("SEED_ADMIN_EMAIL", "admin@centralaguas.com"),
        SEED_ADMIN_PASSWORD=os.getenv("SEED_ADMIN_PASSWORD", "admin123"),
        SEED_ADMIN_NAME=os.getenv("SEED_ADMIN_NAME", "Administrador"),
        ENABLE_UNIFIED_SITE=env_bool("ENABLE_UNIFIED_SITE", True),
        ENABLE_SUBSCRIPTION_BRIDGE=env_bool("ENABLE_SUBSCRIPTION_BRIDGE", True),
        ENABLE_COMMERCIAL_MAP=env_bool("ENABLE_COMMERCIAL_MAP", True),
        ENABLE_SIGNATURE_BANNERS=env_bool("ENABLE_SIGNATURE_BANNERS", True),
        CENTRAL_AGUAS_PRODUCTS_API_URL=os.getenv(
            "CENTRAL_AGUAS_PRODUCTS_API_URL",
            "https://grupogrj.com.br/api/v1/central-aguas/products",
        ),
        CENTRAL_AGUAS_APP_TOKEN=os.getenv("CENTRAL_AGUAS_APP_TOKEN", ""),
        GRJ_CATALOG_ENABLED=env_bool("GRJ_CATALOG_ENABLED", False),
        GRJ_FIREBIRD_HOST=os.getenv("GRJ_FIREBIRD_HOST", "127.0.0.1"),
        GRJ_FIREBIRD_PORT=int(os.getenv("GRJ_FIREBIRD_PORT", "3050")),
        GRJ_FIREBIRD_DATABASE=os.getenv("GRJ_FIREBIRD_DATABASE", ""),
        GRJ_FIREBIRD_USER=os.getenv("GRJ_FIREBIRD_USER", "SYSDBA"),
        GRJ_FIREBIRD_PASSWORD=os.getenv("GRJ_FIREBIRD_PASSWORD", ""),
        GRJ_FIREBIRD_CHARSET=os.getenv("GRJ_FIREBIRD_CHARSET", "UTF8"),
        GRJ_PRODUCTS_QUERY=os.getenv("GRJ_PRODUCTS_QUERY", ""),
        APP_ENV=app_env,
        DEBUG=debug,
        SESSION_COOKIE_SAME_SITE=session_same_site,
        SESSION_COOKIE_SECURE=session_cookie_secure,
        SESSION_MAX_AGE_SECONDS=int(os.getenv("SESSION_MAX_AGE_SECONDS", str(60 * 60 * 12))),
        RESET_TOKEN_TTL_MINUTES=int(os.getenv("RESET_TOKEN_TTL_MINUTES", "30")),
        ALLOW_AUTO_SEED_IN_PRODUCTION=env_bool("ALLOW_AUTO_SEED_IN_PRODUCTION", False),
    )


settings = load_settings()
