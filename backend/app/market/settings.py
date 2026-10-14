import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.db_models import MarketDataSettings
from app.domain.trillion_club import TRILLION_CLUB_CANDIDATES, TRILLION_CLUB_EXCLUSIONS


class MarketSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ibkr"] = "ibkr"
    ibkr_host: str | None = Field(default=None, max_length=253)
    ibkr_port: int | None = Field(default=None, ge=1, le=65535)
    ibkr_client_id: int = Field(default=71, ge=1, le=2147483647)
    club_symbols: list[str] = Field(default_factory=lambda: list(TRILLION_CLUB_CANDIDATES), max_length=50)

    @field_validator("club_symbols")
    @classmethod
    def validate_symbols(cls, symbols):
        result = []
        for value in symbols:
            symbol = value.strip().upper()
            symbol = "BRK-B" if symbol == "BRK.B" else symbol
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", symbol):
                raise ValueError("请输入有效的美股代码")
            if symbol in TRILLION_CLUB_EXCLUSIONS | {"QQQ", "QLD", "TQQQ", "VOO", "SCHD"}:
                raise ValueError(f"{symbol} 不属于个股 PMCC 观察列表")
            if symbol not in result:
                result.append(symbol)
        return result

    @field_validator("ibkr_host")
    @classmethod
    def validate_host(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        if value and not re.fullmatch(r"[a-zA-Z0-9._:\-]+", value):
            raise ValueError("请输入主机名或 IP 地址，不包含协议、路径或账号")
        return value or None

    @property
    def configured(self) -> bool:
        return bool(self.ibkr_host and self.ibkr_port)

    @property
    def effective_provider(self) -> str:
        return "ibkr"

    @property
    def config_key(self) -> str:
        payload = {"provider": self.effective_provider, "club_symbols": self.club_symbols}
        if self.effective_provider == "ibkr":
            payload.update(host=self.ibkr_host, port=self.ibkr_port, client_id=self.ibkr_client_id)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def payload(self) -> dict:
        return {**self.model_dump(), "effective_provider": self.effective_provider,
                "configured": self.configured, "vix_provider": self.effective_provider, "config_key": self.config_key}


def read_settings(session: Session) -> MarketSettings:
    row = session.get(MarketDataSettings, 1)
    return MarketSettings(provider=row.provider, ibkr_host=row.ibkr_host, ibkr_port=row.ibkr_port,
                          ibkr_client_id=row.ibkr_client_id,
                          club_symbols=row.club_symbols if row.club_symbols is not None else list(TRILLION_CLUB_CANDIDATES)) if row else MarketSettings()
