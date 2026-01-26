from sqlalchemy import Column, Integer, String, Float, UniqueConstraint, DateTime
from database import Base
from datetime import datetime


# Card model: Represäntiert eine TCG Karte
class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)

    card_code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False, index=True)
    set_name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    image_url = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("name", "set_name", name="uq_card_name_edition"),
    )


# Price history model: speichert historische Preise für jede Karte
class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    card_id = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
