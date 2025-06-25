# ScoreWise AI - Main FastAPI Application with Subscription Management
import os
import json
import uuid
import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Union, Any
from collections import Counter
import aiofiles
import hashlib
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Form, File, UploadFile, BackgroundTasks, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import stripe
import uvicorn
from sqlalchemy.orm import Session
import numpy as np
from db import SessionLocal, get_db, create_tables, migrate_database
from models import User, Assignment, SubscriptionTier, SubscriptionStatus, TIER_CONFIGS
from subscription_service import subscription_service
from grader import grader
from datetime import datetime

# Environment variables
from dotenv import load_dotenv
load_dotenv()

# Check required environment variables
required_vars = ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "PERPLEXITY_API_KEY", "STRIPE_WEBHOOK_SECRET"]
missing_vars = [var for var in required_vars if not os.getenv(var)]

if missing_vars:
    raise Exception(f"Missing required environment variables: {', '.join(missing_vars)}")

# Stripe Price IDs (set in .env file)
# Monthly Price IDs
PRICE_ID_EDUCATOR_MONTHLY = os.getenv("PRICE_ID_EDUCATOR_MONTHLY")
PRICE_ID_PROFESSIONAL_MONTHLY = os.getenv("PRICE_ID_PROFESSIONAL_MONTHLY")
PRICE_ID_INSTITUTION_MONTHLY = os.getenv("PRICE_ID_INSTITUTION_MONTHLY")

# Annual Price IDs
PRICE_ID_EDUCATOR_ANNUAL = os.getenv("PRICE_ID_EDUCATOR_ANNUAL")
PRICE_ID_PROFESSIONAL_ANNUAL = os.getenv("PRICE_ID_PROFESSIONAL_ANNUAL")
PRICE_ID_INSTITUTION_ANNUAL = os.getenv("PRICE_ID_INSTITUTION_ANNUAL")

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
TIER_CONFIGS["educator"]["stripe_price_id_monthly"] = PRICE_ID_EDUCATOR_MONTHLY
TIER_CONFIGS["educator"]["stripe_price_id_annual"] = PRICE_ID_EDUCATOR_ANNUAL
TIER_CONFIGS["professional"]["stripe_price_id_monthly"] = PRICE_ID_PROFESSIONAL_MONTHLY
TIER_CONFIGS["professional"]["stripe_price_id_annual"] = PRICE_ID_PROFESSIONAL_ANNUAL
TIER_CONFIGS["institution"]["stripe_price_id_monthly"] = PRICE_ID_INSTITUTION_MONTHLY
TIER_CONFIGS["institution"]["stripe_price_id_annual"] = PRICE_ID_INSTITUTION_ANNUAL

# Configure Stripe
stripe.api_key = STRIPE_SECRET_KEY

# Create directories
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# FastAPI app
app = FastAPI(title="ScoreWise AI", description="AI-Powered Assignment Grading Platform")

# Middleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Subjects list for validation
VALID_SUBJECTS = [
    "algebra", "biology", "calculus", "chemistry", "engineering", "physics",
    "english_literature", "history", "philosophy", "creative_writing",
    "psychology", "economics", "sociology", "political_science",
    "music_theory", "art_history", "creative_arts", "drama",
    "spanish", "french", "german", "chinese", "japanese"
]

VALID_ASSESSMENT_TYPES = [
    "essay", "lab_report", "exam", "quiz", "assignment",
    "creative_work", "research_paper", "case_study"
]

# Utility functions
def get_current_user(request: Request, db: Session = None) -> Optional[User]:
    """Get current user from session"""
    session_user = request.session.get("user")
    if not session_user or not db:
        return None
    
    # Get fresh user data from database
    user = db.query(User).filter(User.id == session_user.get("id")).first()
    return user

def require_auth(request: Request, db: Session = Depends(get_db)):
    """Require authentication and return user or redirect"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/?login=required", status_code=303)
    return user

def has_active_subscription(user: User) -> bool:
    """Check if user has an active subscription or valid trial"""
    if user.subscription_status in ["active", "trialing"]:
        return True
    
    # Check if trial is still valid
    if user.subscription_tier == SubscriptionTier.TRIAL.value and user.trial_end:
        return datetime.now() < user.trial_end
    
    return False

async def save_task_metadata(task_id: str, task_data: Dict):
    """Save task metadata to file"""
    try:
        task_dir = Path(f"uploads/{task_id}")
        task_dir.mkdir(exist_ok=True)
        async with aiofiles.open(task_dir / "metadata.json", "w") as f:
            await f.write(json.dumps(task_data, default=str))
    except Exception as e:
        print(f"Error saving task metadata: {str(e)}")
        raise

async def load_task_metadata(task_id: str) -> Optional[Dict]:
    """Load task metadata from file"""
    try:
        async with aiofiles.open(f"uploads/{task_id}/metadata.json", "r") as f:
            content = await f.read()
            return json.loads(content)
    except:
        return None

# Initialize database
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    try:
        migrate_database()
        create_tables()
    except Exception as e:
        print(f"Database initialization error: {str(e)}")

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    current_year = datetime.now().year
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "current_year": current_year
    })

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    
    # Get usage summary if user is logged in
    usage_summary = None
    if user:
        usage_summary = subscription_service.get_usage_summary(user, db)

    # Fetch Stripe prices dynamically for both monthly and annual
    PRICE_IDS = {
        "educator": {
            "monthly": PRICE_ID_EDUCATOR_MONTHLY,
            "annual": PRICE_ID_EDUCATOR_ANNUAL
        },
        "professional": {
            "monthly": PRICE_ID_PROFESSIONAL_MONTHLY,
            "annual": PRICE_ID_PROFESSIONAL_ANNUAL
        },
        "institution": {
            "monthly": PRICE_ID_INSTITUTION_MONTHLY,
            "annual": PRICE_ID_INSTITUTION_ANNUAL
        }
    }
    stripe_prices = {}
    for plan, periods in PRICE_IDS.items():
        stripe_prices[plan] = {}
        for period, price_id in periods.items():
            if price_id:
                price_obj = stripe.Price.retrieve(price_id)
                amount = price_obj["unit_amount"] / 100
                currency = price_obj["currency"].upper()
                interval = price_obj["recurring"]["interval"] if price_obj.get("recurring") else "once"
                stripe_prices[plan][period] = {
                    "amount": f"{amount:.2f}",
                    "currency": currency,
                    "interval": interval
                }
            else:
                stripe_prices[plan][period] = None

    return templates.TemplateResponse("pricing.html", {
        "request": request,
        "user": user,
        "usage_summary": usage_summary,
        "tier_configs": TIER_CONFIGS,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "price_ids": PRICE_IDS,  
        "stripe_prices": stripe_prices
    })

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        return user
    
    if not has_active_subscription(user):
        return RedirectResponse(url="/pricing?expired=true", status_code=303)
    
    # Get user's tier configuration and usage
    usage_summary = subscription_service.get_usage_summary(user, db)
    allowed_subjects = subscription_service.get_allowed_subjects(user)
    
    return templates.TemplateResponse("uploadfile.html", {
        "request": request,
        "user": user,
        "usage_summary": usage_summary,
        "valid_subjects": VALID_SUBJECTS,
        "allowed_subjects": allowed_subjects,
        "valid_assessment_types": VALID_ASSESSMENT_TYPES
    })

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        return user

    if not has_active_subscription(user):
        return RedirectResponse(url="/pricing?expired=true", status_code=303)

    # Get user's recent assignments
    recent_assignments = db.query(Assignment).filter(
        Assignment.user_id == user.id
    ).order_by(Assignment.created_at.desc()).limit(10).all()

    usage_summary = subscription_service.get_usage_summary(user, db)

    # Only completed assignments with results
    completed_assignments = [a for a in recent_assignments if a.status == "completed" and a.results]
    all_stats = [a.results.get("overall_statistics") for a in completed_assignments if a.results.get("overall_statistics")]
    all_individual = []
    for a in completed_assignments:
        if a.results.get("individual_results"):
            for r in a.results["individual_results"]:
                all_individual.append({
                    "assignment_id": a.id,
                    "score": r.get("overall_score"),
                    "rubric_scores": r.get("rubric_scores", {}),
                    "student_name": r.get("student_name", "Student"),
                    "date": a.created_at.strftime("%Y-%m-%d"),
                })

    # Basic analytics
    def aggregate_basic_stats(stats_list):
        if not stats_list:
            return None
        scores = [s.get("average_score", 0) for s in stats_list if s]
        total_assignments = len(stats_list)
        grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for s in stats_list:
            for k in grade_dist:
                grade_dist[k] += s.get("grade_distribution", {}).get(k, 0)
        return {
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "total_assignments": total_assignments,
            "grade_distribution": grade_dist,
        }

    # Advanced analytics
    def aggregate_advanced_stats(stats_list, all_individual):
        if not stats_list or not all_individual:
            return None
        scores = [s.get("average_score", 0) for s in stats_list if s]
        highest = max([s.get("highest_score", 0) for s in stats_list if s], default=None)
        lowest = min([s.get("lowest_score", 0) for s in stats_list if s], default=None)
        total_submissions = sum([s.get("total_submissions", 0) for s in stats_list if s])

        # Score distribution for histogram
        all_scores = [r["score"] for r in all_individual if r["score"] is not None]
        # Assignment dates for trend chart
        assignment_dates = [r["date"] for r in all_individual if r["date"]]
        # Rubric radar: average per criterion
        rubric_totals = {}
        rubric_counts = {}
        for r in all_individual:
            for criterion, val in r["rubric_scores"].items():
                rubric_totals[criterion] = rubric_totals.get(criterion, 0) + val
                rubric_counts[criterion] = rubric_counts.get(criterion, 0) + 1
        rubric_averages = {k: round(rubric_totals[k]/rubric_counts[k], 1) for k in rubric_totals}

        # AI feedback highlights
        all_strengths = []
        all_improvements = []
        for r in all_individual:
            all_strengths.extend(r.get("strengths", []))
            all_improvements.extend(r.get("areas_for_improvement", []))
        top_strengths = [s for s, _ in Counter(all_strengths).most_common(3)]
        top_improvements = [s for s, _ in Counter(all_improvements).most_common(3)]

        # Predictive analytics: forecast next score using linear regression
        if len(assignment_dates) >= 2:
            # Convert dates to ordinal for regression
            dates_ord = [datetime.strptime(d, "%Y-%m-%d").toordinal() for d in assignment_dates]
            scores_np = np.array(all_scores)
            dates_np = np.array(dates_ord)
            # Fit a simple linear trend
            coef = np.polyfit(dates_np, scores_np, 1)
            next_date = max(dates_np) + 7  # Predict one week after last assignment
            predicted_score = int(np.polyval(coef, next_date))
        else:
            predicted_score = None

        return {
            "highest_score": highest,
            "lowest_score": lowest,
            "total_submissions": total_submissions,
            "score_distribution": all_scores,
            "assignment_dates": assignment_dates,
            "rubric_averages": rubric_averages,
            "top_strengths": top_strengths,
            "top_improvements": top_improvements,
            "predicted_score": predicted_score,
        }

    tier = (user.subscription_tier or "").lower()
    show_basic_analytics = tier in ["educator", "professional", "institution"]
    show_advanced_analytics = tier in ["professional", "institution"]

    basic_analytics = aggregate_basic_stats(all_stats) if show_basic_analytics else None
    advanced_analytics = aggregate_advanced_stats(all_stats, all_individual) if show_advanced_analytics else None

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "assignments": recent_assignments,
        "usage_summary": usage_summary,
        "tier_configs": TIER_CONFIGS,
        "basic_analytics": basic_analytics,
        "advanced_analytics": advanced_analytics,
        "show_basic_analytics": show_basic_analytics,
        "show_advanced_analytics": show_advanced_analytics,
    })

@app.post("/api/upload")
async def upload_files(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Form(...),
    assessment_type: str = Form(...),
    assignment_file: UploadFile = File(...),
    student_submissions: List[UploadFile] = File(...),
    solution_file: Optional[UploadFile] = File(None),
    custom_rubric: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    try:
        user = require_auth(request, db)
        if isinstance(user, RedirectResponse):
            raise HTTPException(status_code=401, detail="Authentication required")
        
        if not has_active_subscription(user):
            raise HTTPException(status_code=402, detail="Active subscription required")
        
        # Check if user can create assignment
        can_create, message = subscription_service.can_create_assignment(user, db)
        if not can_create:
            raise HTTPException(status_code=402, detail=message)
        
        # Check subject access
        can_use_subject, subject_message = subscription_service.can_use_subject(user, subject)
        if not can_use_subject:
            raise HTTPException(status_code=403, detail=subject_message)
        
        # Validate submissions count
        valid_submissions = [s for s in student_submissions if s.filename]
        can_process, submission_message = subscription_service.can_process_submissions(user, len(valid_submissions))
        if not can_process:
            raise HTTPException(status_code=403, detail=submission_message)
        
        # Validate input
        if subject not in VALID_SUBJECTS:
            raise HTTPException(status_code=400, detail=f"Invalid subject. Must be one of: {', '.join(VALID_SUBJECTS)}")
        
        if assessment_type not in VALID_ASSESSMENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid assessment type. Must be one of: {', '.join(VALID_ASSESSMENT_TYPES)}")
        
        # File validation
        if not assignment_file or not assignment_file.filename:
            raise HTTPException(status_code=400, detail="Please select an assignment instructions file")
        
        if not valid_submissions:
            raise HTTPException(status_code=400, detail="Please select at least one student submission")
        
        # Check file extensions and sizes
        all_files = [assignment_file] + valid_submissions
        if solution_file and solution_file.filename:
            all_files.append(solution_file)
        if custom_rubric and custom_rubric.filename:
            all_files.append(custom_rubric)
        
        for file in all_files:
            if not file.filename.lower().endswith('.pdf'):
                raise HTTPException(status_code=400, detail=f"Only PDF files allowed. '{file.filename}' is not a PDF")
        
        # Create task
        task_id = str(uuid.uuid4())
        task_dir = Path(f"uploads/{task_id}")
        task_dir.mkdir(exist_ok=True)
        
        # Save files
        saved_files = {}
        
        # Assignment file
        assignment_path = task_dir / f"assignment_{assignment_file.filename}"
        async with aiofiles.open(assignment_path, "wb") as f:
            content = await assignment_file.read()
            await f.write(content)
        saved_files["assignment"] = str(assignment_path)
        
        # Student submissions
        submissions_dir = task_dir / "submissions"
        submissions_dir.mkdir(exist_ok=True)
        submission_paths = []
        
        for i, submission in enumerate(valid_submissions):
            submission_path = submissions_dir / f"submission_{i+1}_{submission.filename}"
            async with aiofiles.open(submission_path, "wb") as f:
                content = await submission.read()
                await f.write(content)
            submission_paths.append(str(submission_path))
        
        saved_files["submissions"] = submission_paths
        
        # Optional files
        if solution_file and solution_file.filename:
            solution_path = task_dir / f"solution_{solution_file.filename}"
            async with aiofiles.open(solution_path, "wb") as f:
                content = await solution_file.read()
                await f.write(content)
            saved_files["solution"] = str(solution_path)
        
        if custom_rubric and custom_rubric.filename:
            # Check if user has custom rubrics feature
            if not subscription_service.has_feature_access(user, "custom_rubrics"):
                raise HTTPException(status_code=403, detail="Custom rubrics not available in your plan. Please upgrade to use this feature.")
            
            rubric_path = task_dir / f"rubric_{custom_rubric.filename}"
            async with aiofiles.open(rubric_path, "wb") as f:
                content = await custom_rubric.read()
                await f.write(content)
            saved_files["rubric"] = str(rubric_path)
        
        # Create assignment record
        assignment = Assignment(
            id=task_id,
            user_id=user.id,
            subject=subject,
            assessment_type=assessment_type,
            submissions_count=len(submission_paths),
            assignment_file_path=saved_files["assignment"],
            solution_file_path=saved_files.get("solution"),
            rubric_file_path=saved_files.get("rubric")
        )
        
        db.add(assignment)
        db.commit()
        
        # Increment usage counter
        subscription_service.increment_assignment_usage(user, db)
        
        # Create task data for processing
        task_data = {
            "task_id": task_id,
            "subject": subject,
            "assessment_type": assessment_type,
            "status": "processing",
            "created_at": datetime.now().isoformat(),
            "user_id": user.id,
            "files": saved_files
        }
        
        await save_task_metadata(task_id, task_data)
        
        # Start processing in background
        background_tasks.add_task(process_grading_task, task_id, db)
        
        return RedirectResponse(
            url=f"/dashboard?task_id={task_id}&status=upload_success",
            status_code=303
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

async def process_grading_task(task_id: str, db: Session):
    """Process grading task using Perplexity API via grader.py"""
    try:
        # Load task data
        task_data = await load_task_metadata(task_id)
        if not task_data:
            return
        
        # Get assignment record
        assignment = db.query(Assignment).filter(Assignment.id == task_id).first()
        if not assignment:
            return
        
        # Update status
        assignment.status = "processing"
        db.commit()
        
        # Use the grader
        results = await grader.grade_assignment(task_data)
        
        # Update assignment with results
        assignment.status = results.get("status", "completed")
        assignment.results = results
        assignment.reports_zip_path = results.get("reports_zip_path")
        assignment.completed_at = datetime.now()
        
        if results.get("status") == "error":
            assignment.error_message = results.get("error", "Unknown error")
        
        db.commit()
        
        # Record usage
        user = db.query(User).filter(User.id == assignment.user_id).first()
        if user:
            subscription_service.record_usage(
                user, "assignment_completed", db,
                resource_used=task_id,
                metadata={"submissions_count": assignment.submissions_count}
            )
        
    except Exception as e:
        # Handle errors
        try:
            assignment = db.query(Assignment).filter(Assignment.id == task_id).first()
            if assignment:
                assignment.status = "error"
                assignment.error_message = str(e)
                db.commit()
        except:
            pass

@app.get("/api/download-reports/{task_id}")
async def download_reports(task_id: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Get assignment and verify ownership
    assignment = db.query(Assignment).filter(Assignment.id == task_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    if assignment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check reports ZIP path
    if not assignment.reports_zip_path or not Path(assignment.reports_zip_path).exists():
        raise HTTPException(status_code=404, detail="Reports not available")
    
    # Schedule cleanup after response
    def cleanup():
        try:
            shutil.rmtree(f"uploads/{task_id}")
            print(f"✓ Cleaned up uploads/{task_id} after download")
        except Exception as e:
            print(f"✗ Error cleaning up uploads/{task_id}: {e}")
    
    background_tasks.add_task(cleanup)
    
    return FileResponse(assignment.reports_zip_path, filename=f"reports_{task_id}.zip")

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    assignment = db.query(Assignment).filter(Assignment.id == task_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    if assignment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return {
        "task_id": assignment.id,
        "status": assignment.status,
        "subject": assignment.subject,
        "assessment_type": assignment.assessment_type,
        "submissions_count": assignment.submissions_count,
        "created_at": assignment.created_at.isoformat(),
        "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
        "results": assignment.results,
        "error_message": assignment.error_message
    }

# Subscription Management Routes
@app.post("/api/create-checkout-session")
async def create_checkout_session(
    request: Request,
    plan: str = Form(...),
    billing_period: str = Form("monthly"),
    db: Session = Depends(get_db)
):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        raise HTTPException(status_code=401, detail="Authentication required")

    if plan not in PRICE_IDS or billing_period not in ["monthly", "annual"]:
        raise HTTPException(status_code=400, detail="Invalid plan or billing period")

    price_id = PRICE_IDS[plan][billing_period]
    if not price_id:
        raise HTTPException(status_code=400, detail="Price not configured")
    
    try:
        checkout_url = await subscription_service.create_checkout_session(user, price_id, db)
        return {"checkout_url": checkout_url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/create-customer-portal-session")
async def create_customer_portal_session(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        portal_url = await subscription_service.create_customer_portal_session(user, db)
        return RedirectResponse(url=portal_url, status_code=303)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/beta-to-paid")
async def convert_beta_to_paid(
    request: Request,
    plan: str = Form(...),
    billing_period: str = Form("monthly"),
    db: Session = Depends(get_db)
):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        return user
    
    # Verify user is beta tester
    if user.subscription_tier != "beta":
        raise HTTPException(status_code=400, detail="Not a beta tester")

    if plan not in PRICE_IDS or billing_period not in ["monthly", "annual"]:
        raise HTTPException(status_code=400, detail="Invalid plan or billing period")
    
    # Create checkout session with beta tester discount
    price_id = PRICE_IDS[plan][billing_period]
    if not price_id:
        raise HTTPException(status_code=400, detail="Price not configured")

    # Optional: Apply beta tester discount
    BETA_PROMO_CODE = os.getenv("BETA_PROMO_CODE")
    checkout_url = await subscription_service.create_checkout_session(
        user, price_id, db, promotion_code=BETA_PROMO_CODE
    )
    
    return {"checkout_url": checkout_url}

@app.get("/api/usage-summary")
async def get_usage_summary(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    return subscription_service.get_usage_summary(user, db)

@app.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db), stripe_signature: str = Header(None)):
    """Handle Stripe webhook events"""
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    success = subscription_service.handle_subscription_webhook(event, db)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@app.get("/success", response_class=HTMLResponse)
async def success(request: Request, session_id: Optional[str] = None):
    return templates.TemplateResponse("success.html", {
        "request": request,
        "session_id": session_id
    })

# Authentication routes
@app.post("/auth/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    
    if user and user.password_hash == hashlib.sha256(password.encode()).hexdigest():
        request.session["user"] = {
            "id": user.id,
            "email": user.email,
            "subscription_tier": user.subscription_tier,
            "subscription_status": user.subscription_status
        }
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "login_error": "Invalid credentials"
    })

@app.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request
    })

@app.post("/auth/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    full_name: str = Form(...),
    invitation_code: str = Form(None),
    db: Session = Depends(get_db)
):
    errors = []
    
    if password != confirm_password:
        errors.append("Passwords do not match")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        errors.append("Email already registered")

    # Check invitation code if provided
    beta_access = False
    beta_expires = None
    used_invitation = None
    
    if invitation_code:
        from models import InvitationCode, BetaTester
        
        invite = db.query(InvitationCode).filter(
            InvitationCode.code == invitation_code,
            InvitationCode.is_active == True,
            InvitationCode.current_uses < InvitationCode.max_uses
        ).first()
        
        if invite:
            # Check expiration
            if invite.expires_at and invite.expires_at < datetime.now():
                errors.append("Invitation code has expired")
            # Check email restriction
            elif invite.email and invite.email != email:
                errors.append("This invitation code is restricted to a specific email address")
            else:
                beta_access = True
                beta_expires = datetime.now() + timedelta(days=60)  # 60-day beta access
                used_invitation = invite
        else:
            errors.append("Invalid invitation code")
    
    if errors:
        return templates.TemplateResponse("register.html", {
            "request": request, 
            "errors": errors
        })
    
    # Create user with trial period
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    # Beta Users
    if beta_access:
        subscription_tier = "beta"
        subscription_status = "active"
        trial_end = beta_expires
    else:
        subscription_tier = SubscriptionTier.TRIAL.value
        subscription_status = SubscriptionStatus.TRIALING.value
        trial_end = datetime.now() + timedelta(days=7)
    
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        subscription_tier=subscription_tier,
        subscription_status=subscription_status,
        trial_end=trial_end
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create beta tester record if applicable
    if beta_access and used_invitation:
        from models import BetaTester
        
        beta_tester = BetaTester(
            id=str(uuid.uuid4()),
            user_id=user.id,
            invitation_code=invitation_code,
            access_expires=beta_expires
        )
        db.add(beta_tester)
        
        # Increment invitation code usage
        used_invitation.current_uses += 1
        db.commit()
    
    request.session["user"] = {
        "id": user.id,
        "email": user.email,
        "subscription_tier": user.subscription_tier,
        "subscription_status": user.subscription_status
    }
    
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/admin/invitations", response_class=HTMLResponse)
async def admin_invitations(request: Request, db: Session = Depends(get_db)):
    # Add admin authentication here
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        return user
    
    # Simple admin check (you may want to implement proper admin roles)
    if user.email != "admin@scorewise-ai.com":  # Replace with your admin email
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from models import InvitationCode
    codes = db.query(InvitationCode).order_by(InvitationCode.created_at.desc()).all()
    
    return templates.TemplateResponse("admin_invitations.html", {
        "request": request,
        "user": user,
        "codes": codes,
        "now": datetime.now()  
    })

@app.post("/admin/generate-invitation")
async def generate_invitation_code(
    request: Request,
    email: str = Form(None),
    max_uses: int = Form(1),
    expires_days: int = Form(60),
    db: Session = Depends(get_db)
):
    user = require_auth(request, db)
    if isinstance(user, RedirectResponse):
        return user
    
    # Admin check
    if user.email != "admin@scorewise-ai.com":  # Replace with your admin email
        raise HTTPException(status_code=403, detail="Admin access required")
    
    import secrets
    from models import InvitationCode
    
    # Generate unique code
    code = f"BETA-{secrets.token_urlsafe(8).upper()}"
    expires_at = datetime.now() + timedelta(days=expires_days) if expires_days else None
    
    invitation = InvitationCode(
        id=str(uuid.uuid4()),
        code=code,
        email=email if email else None,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by_admin=user.email
    )
    
    db.add(invitation)
    db.commit()
    
    return RedirectResponse(url="/admin/invitations", status_code=303)

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


