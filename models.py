# ScoreWise AI - Database Models
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()

class SubscriptionTier(enum.Enum):
    TRIAL = "trial"
    EDUCATOR = "educator" 
    PROFESSIONAL = "professional"
    INSTITUTION = "institution"

class SubscriptionStatus(enum.Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    INCOMPLETE = "incomplete"

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    
    # Stripe Customer Information
    stripe_customer_id = Column(String, unique=True, nullable=True, index=True)
    
    # Subscription Information
    subscription_tier = Column(String, default=SubscriptionTier.TRIAL.value, nullable=False)
    subscription_status = Column(String, default=SubscriptionStatus.TRIALING.value, nullable=False)
    stripe_subscription_id = Column(String, unique=True, nullable=True, index=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    
    # Usage Tracking
    assignments_this_month = Column(Integer, default=0, nullable=False)
    usage_reset_date = Column(DateTime, default=func.now(), nullable=False)
    
    # Account Management
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    assignments = relationship("Assignment", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")
    beta_profile = relationship("BetaTester", back_populates="user", uselist=False)

class Assignment(Base):
    __tablename__ = "assignments"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Assignment Details
    title = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    assessment_type = Column(String, nullable=False)
    
    # Processing Status
    status = Column(String, default="processing", nullable=False)  # processing, completed, error
    
    # File Information
    assignment_file_path = Column(String, nullable=True)
    solution_file_path = Column(String, nullable=True)
    rubric_file_path = Column(String, nullable=True)
    submissions_count = Column(Integer, default=0, nullable=False)
    
    # Results
    results = Column(JSON, nullable=True)
    reports_zip_path = Column(String, nullable=True)
    
    # Metadata
    processing_time_seconds = Column(Float, nullable=True)
    used_ocr = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="assignments")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")

class Submission(Base):
    __tablename__ = "submissions"
    
    id = Column(String, primary_key=True, index=True)
    assignment_id = Column(String, ForeignKey("assignments.id"), nullable=False)
    
    # Submission Details
    student_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    
    # Grading Results
    overall_score = Column(Float, nullable=True)
    rubric_scores = Column(JSON, nullable=True)
    feedback = Column(Text, nullable=True)
    detailed_feedback = Column(Text, nullable=True)
    strengths = Column(JSON, nullable=True)
    areas_for_improvement = Column(JSON, nullable=True)
    
    # Processing Details
    used_ocr = Column(Boolean, default=False, nullable=False)
    processing_time_seconds = Column(Float, nullable=True)
    ai_confidence = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    graded_at = Column(DateTime, nullable=True)
    
    # Relationships
    assignment = relationship("Assignment", back_populates="submissions")

class UsageRecord(Base):
    __tablename__ = "usage_records"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Usage Details
    event_type = Column(String, nullable=False)  # assignment_created, ocr_used, api_call, etc.
    resource_used = Column(String, nullable=True)  # assignment_id, feature_name, etc.
    quantity = Column(Integer, default=1, nullable=False)
    unit_price   = Column(Float, nullable=True)   # what you charged
    subtotal     = Column(Float, nullable=True)   # unit_price * quantity
    
    # Billing Information
    billable = Column(Boolean, default=True, nullable=False)
    tier_at_time = Column(String, nullable=False)
    
    # Metadata
    usage_metadata = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="usage_records")

class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    
    # Stripe Event Information
    stripe_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    
    # Event Data
    old_tier = Column(String, nullable=True)
    new_tier = Column(String, nullable=True)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    
    # Processing Status
    processed = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    stripe_created = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=func.now(), nullable=False)
    processed_at = Column(DateTime, nullable=True)

class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Feature Configuration
    enabled_for_tiers = Column(JSON, nullable=False)  # List of tiers that have access
    configuration = Column(JSON, nullable=True)  # Additional feature config
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class InvitationCode(Base):
    __tablename__ = "invitation_codes"
    
    id = Column(String, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), nullable=True)  # Optional: restrict to specific email
    max_uses = Column(Integer, default=1)
    current_uses = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    created_by_admin = Column(String, nullable=True)  # Admin who created it
    beta_tier = Column(String, default="beta", nullable=False)  # What tier to assign

class BetaTester(Base):
    __tablename__ = "beta_testers"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    invitation_code = Column(String(50))
    access_expires = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="beta_profile")

SubscriptionTier.BETA = "beta"  # Add beta testers

# Subscription Tier Configurations
TIER_CONFIGS = {
    SubscriptionTier.TRIAL.value: {
        "name": "Free Trial",
        "assignments_per_month": 5,
        "submissions_per_assignment": 10,
        "overage_price_per_assignment": 0.00,
        "subjects": ["algebra", "biology", "calculus", "chemistry", "physics"],  # STEM only
        "features": {
            "ocr": False,
            "custom_rubrics": False,
            "analytics": False,
            "priority_processing": False,
            "api_access": False,
            "export_reports": True,
            "email_support": True
        },
        "price_monthly": 0,
        "trial_days": 7
    },
    SubscriptionTier.EDUCATOR.value: {
        "name": "Educator Plan",
        "assignments_per_month": 50,
        "submissions_per_assignment": 30,
        "overage_price_per_assignment": 0.50,      # NEW
        "overage_price_per_submission": 0.00,      # (optional for later)
        "subjects": "all",
        "features": {
            "ocr": True,
            "custom_rubrics": True,
            "analytics": "basic",
            "priority_processing": False,
            "api_access": False,
            "export_reports": True,
            "email_support": True,
            "phone_support": False
        },
        "price_monthly": 19,
        "stripe_price_id_monthly": None,  # Patched at runtime from env
        "stripe_price_id_annual": None,  # Patched at runtime from env
    },
    SubscriptionTier.PROFESSIONAL.value: {
        "name": "Professional Plan",
        "assignments_per_month": 200,
        "submissions_per_assignment": 100,
        "overage_price_per_assignment": 0.40,      # NEW
        "subjects": "all",
        "features": {
            "ocr": True,
            "custom_rubrics": True,
            "analytics": "advanced",
            "priority_processing": True,
            "api_access": False,
            "export_reports": True,
            "email_support": True,
            "phone_support": True,
            "bulk_upload": True
        },
        "price_monthly": 49,
        "stripe_price_id_monthly": None,  # Patched at runtime from env
        "stripe_price_id_annual": None,  # Patched at runtime from env
    },
    SubscriptionTier.INSTITUTION.value: {
        "name": "Institution Plan",
        "assignments_per_month": 500,
        "submissions_per_assignment": 150,
        "overage_price_per_assignment": 0.30,      # NEW
        "subjects": "all",
        "features": {
            "ocr": True,
            "custom_rubrics": True,
            "analytics": "full",
            "priority_processing": True,
            "api_access": True,
            "export_reports": True,
            "email_support": True,
            "phone_support": True,
            "bulk_upload": True,
            "sso": True,
            "white_label": True,
            "dedicated_support": True
        },
        "price_monthly": 199,
        "stripe_price_id_monthly": None,  # Patched at runtime from env
        "stripe_price_id_annual": None,  # Patched at runtime from env
    },
    "beta": {
        "name": "Beta Tester",
        "assignments_per_month": 50,  # Generous for testing
        "submissions_per_assignment": 30,
        "overage_price_per_assignment": 0.00,
        "subjects": "all",
        "features": {
            "ocr": True,
            "custom_rubrics": True,
            "analytics": "advanced",
            "priority_processing": True,
            "api_access": False,
            "export_reports": True,
            "email_support": True,
            "phone_support": False,
            "beta_features": True  # Special beta feature access
        },
        "price_monthly": 0,  # Free for beta testers
        "beta_access_days": 30  # 30-day beta access
    }
}