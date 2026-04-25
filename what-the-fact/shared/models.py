"""SQLAlchemy models for WTF — articles, bias_scores, fact_checks, audit_trail, source_registry."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, JSON, Boolean
from sqlalchemy.orm import relationship
from .db import Base


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False)    # "cbc_english"
    name = Column(String(128), nullable=False)
    url = Column(String(512), nullable=False)
    rss_feed = Column(String(512), nullable=True)
    bias_lean = Column(String(16), nullable=True)             # left|center-left|center|center-right|right
    country = Column(String(8), nullable=False, default="CA")
    language = Column(String(8), nullable=False, default="en")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("wtf.sources.id"), nullable=False)
    external_id = Column(String(512), nullable=False)          # canonical URL or GUID
    title = Column(String(1024), nullable=False)
    body = Column(Text, nullable=False)
    url = Column(String(1024), nullable=False)
    published_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source = relationship("Source")
    # unique(source_id, external_id) enforced in migration


class BiasScore(Base):
    __tablename__ = "bias_scores"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False, unique=True)
    band = Column(String(16), nullable=False)                  # left|center-left|center|center-right|right
    score = Column(Float, nullable=False)                      # -1.0..+1.0
    heuristic_version = Column(String(16), nullable=False)
    rationale = Column(Text, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FactCheck(Base):
    __tablename__ = "fact_checks"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False)
    claim = Column(Text, nullable=False)
    verdict = Column(String(32), nullable=False)               # true|mostly_true|mixed|false|unverified
    evidence = Column(Text, nullable=False)
    checker = Column(String(64), nullable=False)               # "heuristic-v1" for MVP
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditTrail(Base):
    __tablename__ = "audit_trail"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False)
    event_type = Column(String(64), nullable=False)            # ingested|normalized|bias_scored|fact_checked|published
    payload = Column(JSON, nullable=False)                     # arbitrary diagnostic data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FailedIngest(Base):
    __tablename__ = "failed_ingest"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    source_slug = Column(String(64), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    error = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
