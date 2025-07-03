# ScoreWise AI - Subscription Management Service
import os
import stripe
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models import (
    User, Assignment, UsageRecord, SubscriptionEvent, 
    SubscriptionTier, SubscriptionStatus, TIER_CONFIGS
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Overage Price IDs from environment
OVERAGE_PRICE_IDS = {
    'educator': os.getenv('PRICE_ID_EDUCATOR_OVERAGE'),
    'professional': os.getenv('PRICE_ID_PROFESSIONAL_OVERAGE'),
    'institution': os.getenv('PRICE_ID_INSTITUTION_OVERAGE'),
}

class SubscriptionService:
    """Service for managing user subscriptions and enforcing tier limits"""
    
    def __init__(self):
        self.tier_configs = TIER_CONFIGS
    
    def get_user_tier_config(self, user: User) -> Dict[str, Any]:
        """Get the configuration for a user's current tier"""
        return self.tier_configs.get(user.subscription_tier, self.tier_configs[SubscriptionTier.TRIAL.value])
    
    def has_feature_access(self, user: User, feature_name: str) -> bool:
        """Check if user has access to a specific feature"""
        config = self.get_user_tier_config(user)
        features = config.get("features", {})
        
        if feature_name not in features:
            return False
            
        feature_value = features[feature_name]
        
        # Handle boolean features
        if isinstance(feature_value, bool):
            return feature_value
        
        # Handle string features (like analytics levels)
        if isinstance(feature_value, str):
            return feature_value != "none" and feature_value != ""
        
        return False
    
    def get_monthly_assignment_limit(self, user: User) -> int:
        """Get the monthly assignment limit for a user"""
        config = self.get_user_tier_config(user)
        limit = config.get("assignments_per_month", 0)
        
        if limit == "unlimited":
            return float('inf')
        
        return int(limit)
    
    def get_submissions_per_assignment_limit(self, user: User) -> int:
        """Get the submissions per assignment limit for a user"""
        config = self.get_user_tier_config(user)
        limit = config.get("submissions_per_assignment", 0)
        
        if limit == "unlimited":
            return float('inf')
        
        return int(limit)
    
    def get_allowed_subjects(self, user: User) -> List[str]:
        """Get the list of subjects a user can access"""
        config = self.get_user_tier_config(user)
        subjects = config.get("subjects", [])
        
        if subjects == "all":
            # Return all available subjects
            return [
                "algebra", "biology", "calculus", "chemistry", "engineering", "physics",
                "english_literature", "history", "philosophy", "creative_writing",
                "psychology", "economics", "sociology", "political_science",
                "music_theory", "art_history", "creative_arts", "drama",
                "spanish", "french", "german", "chinese", "japanese"
            ]
        
        return subjects if isinstance(subjects, list) else []
    
    def can_create_assignment(self, user: User, db: Session) -> tuple[bool, str]:
        """Check if user can create a new assignment this month"""
        # Reset usage counter if month has changed
        self._reset_monthly_usage_if_needed(user, db)
        
        monthly_limit = self.get_monthly_assignment_limit(user)
        
        if monthly_limit == float('inf'):
            return True, ""
        
        if user.assignments_this_month >= monthly_limit:
            config = self.get_user_tier_config(user)
            return False, f"Monthly assignment limit of {monthly_limit} reached for {config['name']} plan. Please upgrade to continue."
        
        return True, ""
    
    def can_process_submissions(self, user: User, submission_count: int) -> tuple[bool, str]:
        """Check if user can process the given number of submissions"""
        submissions_limit = self.get_submissions_per_assignment_limit(user)
        
        if submissions_limit == float('inf'):
            return True, ""
        
        if submission_count > submissions_limit:
            config = self.get_user_tier_config(user)
            return False, f"Submission limit of {submissions_limit} per assignment exceeded for {config['name']} plan. You submitted {submission_count} files."
        
        return True, ""
    
    def can_use_subject(self, user: User, subject: str) -> tuple[bool, str]:
        """Check if user can use a specific subject"""
        allowed_subjects = self.get_allowed_subjects(user)
        
        if subject in allowed_subjects:
            return True, ""
        
        config = self.get_user_tier_config(user)
        if config['name'] == "Free Trial":
            return False, "Subject access limited to STEM subjects in Free Trial. Please upgrade to access all subjects."
        
        return False, f"Subject '{subject}' not available in {config['name']} plan."
    
    def increment_assignment_usage(self, user: User, db: Session) -> None:
        """Increment usage counter and create overage if limit exceeded."""
        self._reset_monthly_usage_if_needed(user, db)

        user.assignments_this_month += 1
        db.commit()

        # Always record the creation event
        self.record_usage(user, "assignment_created", db)

        # Check for overage
        limit = self.get_monthly_assignment_limit(user)
        if limit != float('inf') and user.assignments_this_month > limit:
            self._charge_assignment_overage(user, db, extra_qty=1)
            logger.info(f"⚠️ User {user.email} exceeded assignment limit ({user.assignments_this_month}/{limit})")
 
    def record_usage(self, user: User, event_type: str, db: Session, 
                    resource_used: Optional[str] = None, quantity: int = 1, 
                    metadata: Optional[Dict] = None) -> None:
        """Record a usage event"""
        usage_record = UsageRecord(
            id=f"usage_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{user.id}_{event_type}",
            user_id=user.id,
            event_type=event_type,
            resource_used=resource_used,
            quantity=quantity,
            tier_at_time=user.subscription_tier,
            metadata=metadata or {}
        )
        
        db.add(usage_record)
        db.commit()
    
    def _reset_monthly_usage_if_needed(self, user: User, db: Session) -> None:
        """Reset monthly usage counters if the month has changed"""
        now = datetime.now()
        
        # Check if we need to reset (different month or year)
        if (user.usage_reset_date.month != now.month or 
            user.usage_reset_date.year != now.year):
            
            user.assignments_this_month = 0
            user.usage_reset_date = now
            db.commit()

    def _charge_assignment_overage(self, user: User, db: Session, extra_qty: int) -> None:
        """Create UsageRecord + Stripe invoice item for assignment overages."""
        cfg = self.get_user_tier_config(user)
        price = cfg.get("overage_price_per_assignment", 0)
        if price == 0 or extra_qty <= 0:
            return  # nothing to charge

        subtotal = round(price * extra_qty, 2)

        # 1. Create a usage record
        self.record_usage(
            user, event_type="assignment_overage",
            db=db,
            resource_used=None,
            quantity=extra_qty,
            metadata={"unit_price": price},
        )
    
        # 2. Update the usage record with pricing info
        latest_record = db.query(UsageRecord).filter(
            UsageRecord.user_id == user.id,
            UsageRecord.event_type == "assignment_overage"
        ).order_by(UsageRecord.timestamp.desc()).first()
    
        if latest_record:
            latest_record.unit_price = price
            latest_record.subtotal = subtotal
            db.commit()

        # 3. Bill through Stripe using price ID (more reliable)
        if user.stripe_customer_id and user.subscription_tier in OVERAGE_PRICE_IDS:
            try:
                price_id = OVERAGE_PRICE_IDS[user.subscription_tier]
                if price_id:
                    stripe.InvoiceItem.create(
                        customer=user.stripe_customer_id,
                        price=price_id,
                        quantity=extra_qty
                    )
                    logger.info(f"✓ Created Stripe invoice item: {extra_qty} overage(s) for {user.subscription_tier}")
                else:
                    logger.warning(f"No overage price ID configured for tier: {user.subscription_tier}")
            except Exception as e:
                logger.error(f"Failed to create Stripe invoice item: {str(e)}")
    
    def get_usage_summary(self, user: Any, db: Any) -> Dict[str, Any]:
        """Get user's current usage summary with overage information"""
        self._reset_monthly_usage_if_needed(user, db)

        config = self.get_user_tier_config(user)

        # Calculate remaining assignments
        monthly_limit = self.get_monthly_assignment_limit(user)
        assignments_used = getattr(user, 'assignments_this_month', 0)

        if monthly_limit == float('inf'):
            assignments_remaining = "Unlimited"
            assignments_limit = "Unlimited"
        else:
            assignments_remaining = max(0, monthly_limit - assignments_used)
            assignments_limit = monthly_limit

        # Calculate usage percentage
        if monthly_limit != float('inf'):
            usage_percentage = min(100, (assignments_used / monthly_limit) * 100)
        else:
            usage_percentage = 0

        # Get submissions info
        submissions_limit = self.get_submissions_per_assignment_limit(user)
        submissions_limit_display = submissions_limit
        if submissions_limit == float('inf'):
            submissions_limit_display = "Unlimited"

        assignments = db.query(Assignment).filter(Assignment.user_id == user.id).all()
        submissions_processed = sum(getattr(a, 'submissions_count', 0) for a in assignments if a.status == "completed")

        # Calculate days remaining and period_end as a string
        days_remaining = 0
        period_end = None
        period_end_str = None
        # Use getattr to avoid AttributeError if field is missing
        user_period_end = getattr(user, 'current_period_end', None)
        user_trial_end = getattr(user, 'trial_end', None)
        if user_period_end:
            period_end = user_period_end
            days_remaining = max(0, (period_end - datetime.now(timezone.utc)).days)
            # Format as "July 31, 2025"
            period_end_str = period_end.strftime('%B %d, %Y')
        elif user_trial_end:
            period_end = user_trial_end
            days_remaining = max(0, (period_end - datetime.now(timezone.utc)).days)
            period_end_str = period_end.strftime('%B %d, %Y')

        status = "Active"
        if assignments_remaining != "Unlimited" and assignments_remaining <= 0:
            status = "Over Limit"
        elif assignments_remaining != "Unlimited" and assignments_remaining < 5:
            status = "Near Limit"

        return {
            "tier_name": config["name"],
            "status": status,
            "assignments_used": assignments_used,
            "assignments_limit": assignments_limit,
            "assignments_remaining": assignments_remaining,
            "submissions_per_assignment": submissions_limit_display,  
            "max_submissions": submissions_limit_display,  # Add this as backup
            "submissions_processed": submissions_processed,
            "usage_percentage": round(usage_percentage, 1),
            "days_remaining": days_remaining,
            "period_end": period_end_str,  # Always a string or None
            "can_upload": assignments_remaining == "Unlimited" or assignments_remaining > 0,
            "overage_price": config.get("overage_price_per_assignment", 0),
            "has_overages": config.get("overage_price_per_assignment", 0) > 0,
            "features": config.get("features", {})
        }
    
    async def create_stripe_customer(self, user: User, db: Session) -> str:
        """Create a Stripe customer for the user"""
        if user.stripe_customer_id:
            return user.stripe_customer_id
        
        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.full_name,
                metadata={
                    "user_id": user.id,
                    "platform": "scorewise_ai"
                }
            )
            
            user.stripe_customer_id = customer.id
            db.commit()
            
            logger.info(f"✓ Created Stripe customer {customer.id} for user {user.id}")
            return customer.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe customer: {str(e)}")
            raise
    
    async def create_checkout_session(
        self, user: User, price_id: str, db: Session, promotion_code: str = None, coupon: str = None
    ) -> str:
        """Create a Stripe checkout session for subscription, with optional discount"""
        await self.create_stripe_customer(user, db)
    
        try:
            params = dict(
                customer=user.stripe_customer_id,
                payment_method_types=["card"],
                mode="subscription",
                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],
                success_url=f"{os.getenv('BASE_URL', 'http://localhost:8000')}/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{os.getenv('BASE_URL', 'http://localhost:8000')}/pricing",
                metadata={
                    "user_id": user.id
                },
                subscription_data={
                    "metadata": {
                        "user_id": user.id
                    }
                }
            )
            # Add the discount if provided
            if promotion_code:
                params["discounts"] = [{"promotion_code": promotion_code}]
            elif coupon:
                params["discounts"] = [{"coupon": coupon}]

            session = stripe.checkout.Session.create(**params)
            return session.url
        
        except Exception as e:
            logger.error(f"Error creating checkout session: {str(e)}")
            raise
    
    async def create_customer_portal_session(self, user: User, db: Session) -> str:
        """Create a Stripe customer portal session"""
        if not user.stripe_customer_id:
            await self.create_stripe_customer(user, db)
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=user.stripe_customer_id,
                return_url=f"{os.getenv('BASE_URL', 'http://localhost:8000')}/dashboard"
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Error creating customer portal session: {str(e)}")
            raise
    
    def handle_subscription_webhook(self, event: Dict[str, Any], db: Session) -> bool:
        """Handle subscription-related webhook events from Stripe"""
        try:
            event_type = event["type"]
            event_data = event["data"]["object"]
            
            # Record the event
            subscription_event = SubscriptionEvent(
                id=f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{event['id']}",
                stripe_event_id=event["id"],
                event_type=event_type,
                stripe_created=datetime.fromtimestamp(event["created"]),
                processed=False
            )
            
            db.add(subscription_event)
            db.commit()
            
            # Handle different event types
            if event_type == "customer.subscription.created":
                return self._handle_subscription_created(event_data, subscription_event, db)
            elif event_type == "customer.subscription.updated":
                return self._handle_subscription_updated(event_data, subscription_event, db)
            elif event_type == "customer.subscription.deleted":
                return self._handle_subscription_deleted(event_data, subscription_event, db)
            elif event_type == "invoice.payment_succeeded":
                return self._handle_payment_succeeded(event_data, subscription_event, db)
            elif event_type == "invoice.payment_failed":
                return self._handle_payment_failed(event_data, subscription_event, db)
            
            subscription_event.processed = True
            subscription_event.processed_at = datetime.now()
            db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling webhook: {str(e)}")
            if 'subscription_event' in locals():
                subscription_event.error_message = str(e)
                db.commit()
            return False
    
    def _handle_subscription_created(self, subscription_data: Dict, event: SubscriptionEvent, db: Session) -> bool:
        """Handle subscription creation"""
        customer_id = subscription_data["customer"]
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        
        if not user:
            logger.error(f"User not found for customer {customer_id}")
            return False
        
        # Determine tier from price ID
        price_id = subscription_data["items"]["data"][0]["price"]["id"]
        tier = self._get_tier_from_price_id(price_id)
        
        if not tier:
            logger.error(f"Unknown price ID: {price_id}")
            return False
        
        old_tier = user.subscription_tier
        
        # Update user subscription
        user.subscription_tier = tier
        user.subscription_status = subscription_data["status"]
        user.stripe_subscription_id = subscription_data["id"]
        user.current_period_start = datetime.fromtimestamp(subscription_data["current_period_start"])
        user.current_period_end = datetime.fromtimestamp(subscription_data["current_period_end"])
        
        # Record the change
        event.user_id = user.id
        event.old_tier = old_tier
        event.new_tier = tier
        event.new_status = subscription_data["status"]
        
        db.commit()
        
        logger.info(f"✓ Subscription created for user {user.id}: {tier}")
        return True
    
    def _handle_subscription_updated(self, subscription_data: Dict, event: SubscriptionEvent, db: Session) -> bool:
        """Handle subscription updates"""
        subscription_id = subscription_data["id"]
        user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
        
        if not user:
            logger.error(f"User not found for subscription {subscription_id}")
            return False
        
        old_tier = user.subscription_tier
        old_status = user.subscription_status
        
        # Determine new tier from price ID
        price_id = subscription_data["items"]["data"][0]["price"]["id"]
        tier = self._get_tier_from_price_id(price_id)
        
        if tier:
            user.subscription_tier = tier
        
        user.subscription_status = subscription_data["status"]
        user.current_period_start = datetime.fromtimestamp(subscription_data["current_period_start"])
        user.current_period_end = datetime.fromtimestamp(subscription_data["current_period_end"])
        
        # Record the change
        event.user_id = user.id
        event.old_tier = old_tier
        event.new_tier = tier or user.subscription_tier
        event.old_status = old_status
        event.new_status = subscription_data["status"]
        
        db.commit()
        
        logger.info(f"✓ Subscription updated for user {user.id}: {user.subscription_tier} ({user.subscription_status})")
        return True
    
    def _handle_subscription_deleted(self, subscription_data: Dict, event: SubscriptionEvent, db: Session) -> bool:
        """Handle subscription cancellation"""
        subscription_id = subscription_data["id"]
        user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
        
        if not user:
            logger.error(f"User not found for subscription {subscription_id}")
            return False
        
        old_tier = user.subscription_tier
        old_status = user.subscription_status
        
        # Downgrade to trial
        user.subscription_tier = SubscriptionTier.TRIAL.value
        user.subscription_status = SubscriptionStatus.CANCELED.value
        user.stripe_subscription_id = None
        user.current_period_start = None
        user.current_period_end = None
        
        # Record the change
        event.user_id = user.id
        event.old_tier = old_tier
        event.new_tier = SubscriptionTier.TRIAL.value
        event.old_status = old_status
        event.new_status = SubscriptionStatus.CANCELED.value
        
        db.commit()
        
        logger.info(f"✓ Subscription canceled for user {user.id}")
        return True
    
    def _handle_payment_succeeded(self, invoice_data: Dict, event: SubscriptionEvent, db: Session) -> bool:
        """Handle successful payment"""
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return True  # Not a subscription invoice
        
        user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
        if not user:
            return False
        
        # Ensure subscription is active
        if user.subscription_status != SubscriptionStatus.ACTIVE.value:
            user.subscription_status = SubscriptionStatus.ACTIVE.value
            db.commit()
        
        event.user_id = user.id
        logger.info(f"✓ Payment succeeded for user {user.id}")
        return True
    
    def _handle_payment_failed(self, invoice_data: Dict, event: SubscriptionEvent, db: Session) -> bool:
        """Handle failed payment"""
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return True  # Not a subscription invoice
        
        user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
        if not user:
            return False
        
        old_status = user.subscription_status
        user.subscription_status = SubscriptionStatus.PAST_DUE.value
        
        event.user_id = user.id
        event.old_status = old_status
        event.new_status = SubscriptionStatus.PAST_DUE.value
        
        db.commit()
        
        logger.warning(f"⚠️ Payment failed for user {user.id}")
        return True
    
    def _get_tier_from_price_id(self, price_id: str) -> Optional[str]:
        """Get subscription tier from Stripe price ID"""
        for tier, config in self.tier_configs.items():
            # Check both monthly and annual price IDs
            if (config.get("stripe_price_id_monthly") == price_id or 
                config.get("stripe_price_id_annual") == price_id):
                return tier
        return None


    def is_beta_tester(self, user: User, db: Session) -> bool:
        """Check if user is a beta tester"""
        if user.subscription_tier == "beta":
            return True
    
        from models import BetaTester
        beta_profile = db.query(BetaTester).filter(BetaTester.user_id == user.id).first()
    
        if beta_profile:
            # Check if beta access hasn't expired
            if beta_profile.access_expires and beta_profile.access_expires > datetime.now():
                return True
    
        return False

    def get_beta_features(self, user: User, db: Session) -> Dict[str, Any]:
        """Get special beta features for beta testers"""
        if not self.is_beta_tester(user, db):
            return {}
    
        return {
            "advanced_analytics": True,
            "priority_support": True,
            "beta_features": True,
            "extended_limits": True
        }

# Global subscription service instance
subscription_service = SubscriptionService()