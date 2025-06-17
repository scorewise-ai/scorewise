# ScoreWise AI - Main FastAPI Application
# Place this file in the root directory of your project

import os
import json
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import aiofiles
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Form, File, UploadFile, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.sessions import SessionMiddleware
import stripe
import requests
from pydantic import BaseModel
import uvicorn

# Environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY") 
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Stripe Price IDs
PRICE_ID_STANDARD = os.getenv("PRICE_ID_STANDARD")
PRICE_ID_PRO = os.getenv("PRICE_ID_PRO") 
PRICE_ID_ENTERPRISE = os.getenv("PRICE_ID_ENTERPRISE")

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

# Models
class GradingTask(BaseModel):
    task_id: str
    subject: str
    assignment_type: str
    status: str = "processing"
    created_at: datetime
    files: Dict[str, str] = {}
    results: Optional[Dict] = None

# In-memory storage for tasks (replace with database in production)
tasks_storage: Dict[str, GradingTask] = {}

# Utility functions
def get_current_user(request: Request) -> Optional[Dict]:
    return request.session.get("user")

def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

def has_active_subscription(user: Dict) -> bool:
    return user.get("subscription_status") == "active"

async def save_task_metadata(task_id: str, task_data: Dict):
    task_dir = Path(f"uploads/{task_id}")
    task_dir.mkdir(exist_ok=True)
    async with aiofiles.open(task_dir / "metadata.json", "w") as f:
        await f.write(json.dumps(task_data, default=str))

async def load_task_metadata(task_id: str) -> Optional[Dict]:
    try:
        async with aiofiles.open(f"uploads/{task_id}/metadata.json", "r") as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        return None

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY
    })

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("pricing.html", {
        "request": request,
        "user": user,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "price_ids": {
            "standard": PRICE_ID_STANDARD,
            "pro": PRICE_ID_PRO,
            "enterprise": PRICE_ID_ENTERPRISE
        }
    })

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    user = require_auth(request)
    if not has_active_subscription(user):
        return RedirectResponse(url="/pricing", status_code=303)
    
    return templates.TemplateResponse("uploadfile.html", {
        "request": request,
        "user": user
    })

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_auth(request)
    if not has_active_subscription(user):
        return RedirectResponse(url="/pricing", status_code=303)
    
    # Get user's recent tasks
    user_tasks = []
    for task_id, task in tasks_storage.items():
        if task.files.get("user_id") == user.get("id"):
            user_tasks.append(task)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "tasks": user_tasks[-10:]  # Last 10 tasks
    })

@app.post("/api/upload")
async def upload_files(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Form(...),
    assignment_type: str = Form(...),
    assignment_file: UploadFile = File(...),
    student_submissions: List[UploadFile] = File(...),
    solution_file: Optional[UploadFile] = File(None),
    custom_rubric: Optional[UploadFile] = File(None)
):
    user = require_auth(request)
    if not has_active_subscription(user):
        raise HTTPException(status_code=402, detail="Subscription required")
    
    # Validate file types (PDF only)
    all_files = [assignment_file] + student_submissions
    if solution_file:
        all_files.append(solution_file)
    if custom_rubric:
        all_files.append(custom_rubric)
    
    for file in all_files:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed. File '{file.filename}' is not a PDF.")
        if file.size > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(status_code=400, detail=f"File '{file.filename}' exceeds 10MB limit.")
    
    # Create task
    task_id = str(uuid.uuid4())
    task_dir = Path(f"uploads/{task_id}")
    task_dir.mkdir(exist_ok=True)
    
    # Save files
    saved_files = {}
    
    # Save assignment file
    assignment_path = task_dir / f"assignment_{assignment_file.filename}"
    async with aiofiles.open(assignment_path, "wb") as f:
        content = await assignment_file.read()
        await f.write(content)
    saved_files["assignment"] = str(assignment_path)
    
    # Save student submissions
    submissions_dir = task_dir / "submissions"
    submissions_dir.mkdir(exist_ok=True)
    submission_paths = []
    
    for i, submission in enumerate(student_submissions):
        submission_path = submissions_dir / f"submission_{i+1}_{submission.filename}"
        async with aiofiles.open(submission_path, "wb") as f:
            content = await submission.read()
            await f.write(content)
        submission_paths.append(str(submission_path))
    
    saved_files["submissions"] = submission_paths
    
    # Save optional files
    if solution_file:
        solution_path = task_dir / f"solution_{solution_file.filename}"
        async with aiofiles.open(solution_path, "wb") as f:
            content = await solution_file.read()
            await f.write(content)
        saved_files["solution"] = str(solution_path)
    
    if custom_rubric:
        rubric_path = task_dir / f"rubric_{custom_rubric.filename}"
        async with aiofiles.open(rubric_path, "wb") as f:
            content = await custom_rubric.read()
            await f.write(content)
        saved_files["rubric"] = str(rubric_path)
    
    # Create task record
    task_data = {
        "task_id": task_id,
        "subject": subject,
        "assignment_type": assignment_type,
        "status": "processing",
        "created_at": datetime.now().isoformat(),
        "user_id": user.get("id"),
        "files": saved_files
    }
    
    # Save task metadata
    await save_task_metadata(task_id, task_data)
    tasks_storage[task_id] = GradingTask(**task_data)
    
    # Start grading process in background
    background_tasks.add_task(process_grading_task, task_id)
    
    return {"task_id": task_id, "status": "processing"}

async def process_grading_task(task_id: str):
    """Process grading task using Perplexity API"""
    try:
        task_data = await load_task_metadata(task_id)
        if not task_data:
            return
        
        # Simulate grading process (replace with actual grading logic)
        await asyncio.sleep(5)  # Simulate processing time
        
        # Mock results for demonstration
        results = {
            "overall_score": 85,
            "feedback": "Good work overall. Some areas for improvement in analysis section.",
            "rubric_scores": {
                "Content": 90,
                "Organization": 80,
                "Grammar": 85,
                "Analysis": 75
            },
            "detailed_feedback": "The assignment demonstrates a solid understanding of the topic...",
            "processed_at": datetime.now().isoformat()
        }
        
        # Update task with results
        task_data["status"] = "completed"
        task_data["results"] = results
        
        await save_task_metadata(task_id, task_data)
        if task_id in tasks_storage:
            tasks_storage[task_id].status = "completed"
            tasks_storage[task_id].results = results
        
    except Exception as e:
        # Handle errors
        task_data = await load_task_metadata(task_id)
        if task_data:
            task_data["status"] = "error"
            task_data["error"] = str(e)
            await save_task_metadata(task_id, task_data)
            if task_id in tasks_storage:
                tasks_storage[task_id].status = "error"

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str, request: Request):
    user = require_auth(request)
    
    task_data = await load_task_metadata(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Check if user owns this task
    if task_data.get("user_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return task_data

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: Request, plan: str = Form(...)):
    user = get_current_user(request)
    
    price_ids = {
        "standard": PRICE_ID_STANDARD,
        "pro": PRICE_ID_PRO,
        "enterprise": PRICE_ID_ENTERPRISE
    }
    
    if plan not in price_ids:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{
                "price": price_ids[plan],
                "quantity": 1,
            }],
            success_url=request.url_for("success") + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.url_for("pricing"),
            client_reference_id=user.get("id") if user else None,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/success", response_class=HTMLResponse)
async def success(request: Request, session_id: Optional[str] = None):
    return templates.TemplateResponse("success.html", {
        "request": request,
        "session_id": session_id
    })

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # Update user subscription status
        # Implementation depends on your user management system
        pass
    
    return {"status": "success"}

# Authentication routes (simplified)
@app.post("/auth/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    # Simplified authentication - replace with proper authentication
    if email and password:
        user_data = {
            "id": str(uuid.uuid4()),
            "email": email,
            "subscription_status": "active"  # For demo purposes
        }
        request.session["user"] = user_data
        return RedirectResponse(url="/dashboard", status_code=303)
    
    raise HTTPException(status_code=400, detail="Invalid credentials")

@app.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)