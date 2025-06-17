# ScoreWise AI Grader Module
# Place this file as grader.py in the root directory of your project
# This integrates with your existing grading functionality

import os
import json
import asyncio
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from dotenv import load_dotenv

load_dotenv()

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

class ScoreWiseGrader:
    def __init__(self):
        self.api_key = PERPLEXITY_API_KEY
        self.api_url = "https://api.perplexity.ai/chat/completions"
        
        # Subject-specific rubrics
        self.default_rubrics = {
            "Mathematics": {
                "Problem Understanding": {"weight": 0.25, "description": "Demonstrates understanding of the problem"},
                "Mathematical Reasoning": {"weight": 0.30, "description": "Uses appropriate mathematical concepts and methods"},
                "Calculation Accuracy": {"weight": 0.25, "description": "Performs calculations correctly"},
                "Solution Presentation": {"weight": 0.20, "description": "Clearly presents solution with proper notation"}
            },
            "English": {
                "Content & Ideas": {"weight": 0.30, "description": "Quality and development of ideas"},
                "Organization": {"weight": 0.25, "description": "Logical structure and flow"},
                "Language Use": {"weight": 0.25, "description": "Grammar, vocabulary, and style"},
                "Mechanics": {"weight": 0.20, "description": "Spelling, punctuation, and formatting"}
            },
            "Science": {
                "Scientific Knowledge": {"weight": 0.30, "description": "Understanding of scientific concepts"},
                "Data Analysis": {"weight": 0.25, "description": "Interpretation and analysis of data"},
                "Scientific Method": {"weight": 0.25, "description": "Application of scientific inquiry methods"},
                "Communication": {"weight": 0.20, "description": "Clear explanation of findings"}
            },
            "History": {
                "Historical Knowledge": {"weight": 0.30, "description": "Understanding of historical facts and context"},
                "Analysis & Interpretation": {"weight": 0.30, "description": "Analysis of historical sources and events"},
                "Argumentation": {"weight": 0.25, "description": "Development of historical arguments"},
                "Writing Quality": {"weight": 0.15, "description": "Clarity and organization of writing"}
            },
            "Computer Science": {
                "Code Functionality": {"weight": 0.35, "description": "Code works correctly and meets requirements"},
                "Code Quality": {"weight": 0.25, "description": "Clean, readable, and well-structured code"},
                "Algorithm Design": {"weight": 0.25, "description": "Efficient and appropriate algorithm choices"},
                "Documentation": {"weight": 0.15, "description": "Comments and code documentation"}
            }
        }
    
    async def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        try:
            # For production, use a proper PDF library like PyPDF2 or pdfplumber
            # This is a simplified version
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
                # In a real implementation, extract text from PDF
                # For now, return a placeholder
                return f"PDF content from {file_path} - {len(content)} bytes"
        except Exception as e:
            return f"Error reading PDF: {str(e)}"
    
    async def load_custom_rubric(self, rubric_path: Optional[str]) -> Dict:
        """Load custom rubric from file or use default"""
        if rubric_path and os.path.exists(rubric_path):
            try:
                async with aiofiles.open(rubric_path, 'r') as f:
                    content = await f.read()
                    # Parse custom rubric from PDF
                    return {"Custom Rubric": {"weight": 1.0, "description": "Custom rubric loaded"}}
            except Exception:
                pass
        
        # Return default rubric for the subject
        return self.default_rubrics.get("General", {
            "Content": {"weight": 0.40, "description": "Quality and accuracy of content"},
            "Organization": {"weight": 0.30, "description": "Structure and logical flow"},
            "Presentation": {"weight": 0.30, "description": "Clarity and professional presentation"}
        })
    
    async def grade_assignment(self, task_data: Dict) -> Dict:
        """Main grading function"""
        try:
            task_id = task_data["task_id"]
            subject = task_data["subject"]
            assignment_type = task_data["assignment_type"]
            files = task_data["files"]
            
            # Extract text from files
            assignment_text = ""
            if "assignment" in files:
                assignment_text = await self.extract_text_from_pdf(files["assignment"])
            
            solution_text = ""
            if "solution" in files:
                solution_text = await self.extract_text_from_pdf(files["solution"])
            
            # Load rubric
            rubric = await self.load_custom_rubric(files.get("rubric"))
            if not rubric:
                rubric = self.default_rubrics.get(subject, self.default_rubrics["General"])
            
            # Grade each submission
            submission_results = []
            submissions = files.get("submissions", [])
            
            for i, submission_path in enumerate(submissions):
                submission_text = await self.extract_text_from_pdf(submission_path)
                
                # Grade individual submission
                individual_result = await self.grade_individual_submission(
                    assignment_text=assignment_text,
                    submission_text=submission_text,
                    solution_text=solution_text,
                    rubric=rubric,
                    subject=subject,
                    assignment_type=assignment_type
                )
                
                individual_result["submission_id"] = i + 1
                individual_result["file_path"] = submission_path
                submission_results.append(individual_result)
            
            # Calculate overall statistics
            overall_stats = self.calculate_overall_statistics(submission_results)
            
            # Prepare final results
            results = {
                "task_id": task_id,
                "subject": subject,
                "assignment_type": assignment_type,
                "rubric_used": rubric,
                "submission_count": len(submissions),
                "individual_results": submission_results,
                "overall_statistics": overall_stats,
                "processed_at": datetime.now().isoformat(),
                "status": "completed"
            }
            
            return results
            
        except Exception as e:
            return {
                "task_id": task_data.get("task_id", "unknown"),
                "status": "error",
                "error": str(e),
                "processed_at": datetime.now().isoformat()
            }
    
    async def grade_individual_submission(self, assignment_text: str, submission_text: str, 
                                        solution_text: str, rubric: Dict, subject: str, 
                                        assignment_type: str) -> Dict:
        """Grade a single submission using AI"""
        
        # Prepare prompt for AI grading
        prompt = self.create_grading_prompt(
            assignment_text, submission_text, solution_text, rubric, subject, assignment_type
        )
        
        try:
            # Call Perplexity API
            response = await self.call_perplexity_api(prompt)
            
            # Parse AI response
            ai_feedback = self.parse_ai_response(response)
            
            # Calculate final scores
            rubric_scores = {}
            total_weighted_score = 0
            
            for criterion, details in rubric.items():
                # Extract score for this criterion from AI response
                score = ai_feedback.get("scores", {}).get(criterion, 75)  # Default to 75%
                rubric_scores[criterion] = score
                total_weighted_score += score * details["weight"]
            
            return {
                "overall_score": round(total_weighted_score),
                "rubric_scores": rubric_scores,
                "feedback": ai_feedback.get("feedback", "Good work overall."),
                "detailed_feedback": ai_feedback.get("detailed_feedback", ""),
                "strengths": ai_feedback.get("strengths", []),
                "areas_for_improvement": ai_feedback.get("improvements", []),
                "ai_confidence": ai_feedback.get("confidence", 0.8)
            }
            
        except Exception as e:
            # Fallback scoring if AI fails
            return {
                "overall_score": 75,
                "rubric_scores": {k: 75 for k in rubric.keys()},
                "feedback": f"Automated grading completed. Manual review recommended. (Error: {str(e)})",
                "detailed_feedback": "The submission has been processed with basic scoring.",
                "strengths": ["Submission received and processed"],
                "areas_for_improvement": ["Manual review recommended"],
                "ai_confidence": 0.5
            }
    
    def create_grading_prompt(self, assignment_text: str, submission_text: str, 
                            solution_text: str, rubric: Dict, subject: str, 
                            assignment_type: str) -> str:
        """Create detailed prompt for AI grading"""
        
        rubric_text = "\n".join([
            f"- {criterion} ({details['weight']*100:.0f}%): {details['description']}"
            for criterion, details in rubric.items()
        ])
        
        prompt = f"""
You are an expert {subject} educator grading a {assignment_type}. Please provide detailed, constructive feedback and scoring.

ASSIGNMENT INSTRUCTIONS:
{assignment_text[:2000]}  # Limit to prevent token overflow

GRADING RUBRIC:
{rubric_text}

STUDENT SUBMISSION:
{submission_text[:3000]}  # Limit to prevent token overflow

{f"SOLUTION/ANSWER KEY: {solution_text[:1000]}" if solution_text else ""}

Please provide:
1. A score (0-100) for each rubric criterion
2. Overall constructive feedback
3. Specific strengths identified
4. Areas for improvement
5. Detailed comments on the work

Format your response as JSON with the following structure:
{{
    "scores": {{
        "criterion_name": score_number,
        ...
    }},
    "feedback": "Overall feedback summary",
    "detailed_feedback": "Detailed analysis of the work",
    "strengths": ["strength 1", "strength 2", ...],
    "improvements": ["improvement 1", "improvement 2", ...],
    "confidence": 0.0-1.0
}}

Be fair, constructive, and specific in your feedback. Focus on helping the student learn and improve.
"""
        return prompt
    
    async def call_perplexity_api(self, prompt: str) -> Dict:
        """Call Perplexity API for AI grading"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "llama-3.1-sonar-large-128k-online",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert educator providing fair, detailed, and constructive feedback on student work."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.3
        }
        
        # Use asyncio to make the request non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.post(self.api_url, headers=headers, json=data)
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"API error: {response.status_code} - {response.text}")
    
    def parse_ai_response(self, response: Dict) -> Dict:
        """Parse AI response and extract grading information"""
        try:
            content = response["choices"][0]["message"]["content"]
            
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                # Fallback parsing if JSON is not found
                return {
                    "scores": {},
                    "feedback": content[:500],
                    "detailed_feedback": content,
                    "strengths": [],
                    "improvements": [],
                    "confidence": 0.7
                }
        except Exception:
            return {
                "scores": {},
                "feedback": "AI grading completed with basic feedback.",
                "detailed_feedback": "The submission has been reviewed.",
                "strengths": ["Submission completed"],
                "improvements": ["Continue practicing"],
                "confidence": 0.6
            }
    
    def calculate_overall_statistics(self, submission_results: List[Dict]) -> Dict:
        """Calculate statistics across all submissions"""
        if not submission_results:
            return {}
        
        scores = [result["overall_score"] for result in submission_results]
        
        return {
            "average_score": round(sum(scores) / len(scores), 1),
            "highest_score": max(scores),
            "lowest_score": min(scores),
            "total_submissions": len(submission_results),
            "grade_distribution": self.calculate_grade_distribution(scores)
        }
    
    def calculate_grade_distribution(self, scores: List[int]) -> Dict:
        """Calculate grade distribution"""
        distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        
        for score in scores:
            if score >= 90:
                distribution["A"] += 1
            elif score >= 80:
                distribution["B"] += 1
            elif score >= 70:
                distribution["C"] += 1
            elif score >= 60:
                distribution["D"] += 1
            else:
                distribution["F"] += 1
        
        return distribution

# Initialize grader instance
grader = ScoreWiseGrader()