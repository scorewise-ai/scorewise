import os
import json
import asyncio
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from dotenv import load_dotenv
import PyPDF2
import io
import zipfile
import shutil
from fpdf import FPDF
import re
import logging
import tempfile
import fitz  # PyMuPDF for text percentage detection
from pdf2image import convert_from_path
from PIL import Image
import platform

# Configure logging
import sys

# Clear any existing handlers to ensure fresh configuration
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Create and configure module logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

load_dotenv()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
HANDWRITING_OCR_API_KEY = os.getenv("HANDWRITING_OCR_API_KEY")
HANDWRITING_OCR_API_URL = os.getenv("HANDWRITING_OCR_API_URL")
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        # Clear any existing font cache
        self.fonts = {}
        self.core_fonts = {}
        
        # Logo path - using the existing logo in static folder
        self.logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "scorewise_logo.png")
        
        # Debug path information
        current_file = os.path.abspath(__file__)
        fonts_dir = os.path.join(os.path.dirname(current_file), "fonts")
        static_dir = os.path.join(os.path.dirname(current_file), "static")
        
        logger.info(f"Current file: {current_file}")
        logger.info(f"Fonts directory: {fonts_dir}")
        logger.info(f"Static directory: {static_dir}")
        logger.info(f"Logo path: {self.logo_path}")
        logger.info(f"Logo exists: {os.path.exists(self.logo_path)}")
        logger.info(f"Fonts directory exists: {os.path.exists(fonts_dir)}")
        
        if os.path.exists(fonts_dir):
            logger.info(f"Font files: {os.listdir(fonts_dir)}")
        
        # Register fonts with absolute paths
        try:
            self.add_font('DejaVu', '', os.path.join(fonts_dir, 'DejaVuSans.ttf'), uni=True)
            self.add_font('DejaVu', 'B', os.path.join(fonts_dir, 'DejaVuSans-Bold.ttf'), uni=True)
            self.add_font('DejaVu', 'I', os.path.join(fonts_dir, 'DejaVuSans-Oblique.ttf'), uni=True)
            self.add_font('DejaVu', 'BI', os.path.join(fonts_dir, 'DejaVuSans-BoldOblique.ttf'), uni=True)
            logger.info("✓ Successfully registered DejaVu fonts")
        except Exception as e:
            logger.error(f"Font registration failed: {str(e)}")
            # Fallback to system fonts if needed
            self._use_builtin_fonts = True
        
        self.add_page()

    def header(self):
        """Professional header with ScoreWise AI logo and branding"""
        # Check if logo exists and add it
        if os.path.exists(self.logo_path):
            try:
                # Add logo to the top-left
                self.image(self.logo_path, x=10, y=8, w=25, h=15)  # Adjust dimensions as needed
                
                # Position text next to logo
                self.set_xy(40, 8)  # Start text after logo
                font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
                self.set_font(font_family, 'B', 18)
                self.set_text_color(59, 130, 246)  # Blue color
                self.cell(0, 8, 'ScoreWise AI', 0, 1, 'L')
                
                self.set_xy(40, 16)
                self.set_font(font_family, '', 12)
                self.set_text_color(100, 100, 100)  # Gray color
                self.cell(0, 6, 'AI-Powered Assignment Grading', 0, 1, 'L')
                
                # Add separator line
                self.ln(5)
                self.set_draw_color(200, 200, 200)
                self.line(10, 28, 200, 28)  # Horizontal line
                self.ln(10)
                
            except Exception as e:
                logger.warning(f"Could not add logo to PDF: {str(e)}")
                # Fallback to text-based header
                self._text_only_header()
        else:
            logger.warning(f"Logo file not found at: {self.logo_path}")
            self._text_only_header()
        
        # Reset text color to black for content
        self.set_text_color(0, 0, 0)
    
    def _text_only_header(self):
        """Fallback header when logo is not available"""
        font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
        self.set_font(font_family, 'B', 18)
        self.set_text_color(59, 130, 246)  # Blue color
        self.cell(0, 10, 'ScoreWise AI', 0, 1, 'C')
        self.set_font(font_family, '', 12)
        self.set_text_color(100, 100, 100)  # Gray color
        self.cell(0, 6, 'AI-Powered Assignment Grading', 0, 1, 'C')
        self.ln(10)
        # Reset text color
        self.set_text_color(0, 0, 0)

    def chapter_title(self, title):
        """Enhanced chapter title with better styling"""
        font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
        self.set_font(font_family, 'B', 14)
        
        # Add subtle background for chapter titles
        self.set_fill_color(248, 250, 252)  # Very light gray
        self.cell(0, 10, title, 0, 1, 'L', True)
        self.ln(2)

    def chapter_body(self, body):
        """Enhanced chapter body with proper font selection"""
        font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
        self.set_font(font_family, '', 11)
        self.multi_cell(0, 6, body)
        self.ln()

    def add_score_section(self, title, score, max_score=100):
        """Enhanced score section with color-coded performance indicators"""
        font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
        
        # Score background color based on performance
        if score >= 90:
            self.set_fill_color(220, 252, 231)  # Light green
            self.set_text_color(22, 101, 52)    # Dark green
        elif score >= 80:
            self.set_fill_color(254, 249, 195)  # Light yellow
            self.set_text_color(133, 77, 14)    # Dark yellow
        elif score >= 70:
            self.set_fill_color(255, 237, 213)  # Light orange
            self.set_text_color(154, 52, 18)    # Dark orange
        else:
            self.set_fill_color(254, 226, 226)  # Light red
            self.set_text_color(153, 27, 27)    # Dark red
        
        self.set_font(font_family, 'B', 12)
        self.cell(120, 10, title, 0, 0, 'L', True)
        self.cell(0, 10, f"{score}%", 0, 1, 'R', True)
        
        # Reset colors
        self.set_text_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)

    def create_professional_footer(self):
        """Add a professional footer with branding"""
        # Position footer at bottom of page
        self.set_y(-20)
        
        # Draw a line above footer
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        
        self.ln(3)
        
        # Footer text
        font_family = 'Arial' if hasattr(self, '_use_builtin_fonts') and self._use_builtin_fonts else 'DejaVu'
        self.set_font(font_family, 'I', 9)
        self.set_text_color(100, 100, 100)
        
        # Left side - branding
        self.cell(0, 5, 'Generated by ScoreWise AI - Supporting Academic Excellence', 0, 0, 'C')
        
        # Reset colors
        self.set_text_color(0, 0, 0)

def get_poppler_path():
    if platform.system() == "Windows":
        return r"C:\poppler-24.08.0\Library\bin"
    return None

class ScoreWiseGrader:
    # Save the word list (one word per line) as english_words.txt in your project directory
    def load_word_set(self, filepath="words.txt"):
        with open(filepath, "r") as f:
            return set(word.strip().lower() for word in f if word.strip())


    def __init__(self):
        self.api_key = PERPLEXITY_API_KEY
        self.api_url = "https://api.perplexity.ai/chat/completions"
        self.handwriting_ocr_key = HANDWRITING_OCR_API_KEY
        self.handwriting_ocr_url = HANDWRITING_OCR_API_URL
        self.default_rubrics = self._initialize_rubrics()
        self.COMMON_ENGLISH_WORDS = self.load_word_set()
    
    def _initialize_rubrics(self):
        # Comprehensive rubric system covering all subjects and assessment types
        return {
            # STEM Subjects (existing)
            "algebra": {
                "Problem Setup": {"weight": 0.25, "description": "Correctly identifies variables and sets up equations"},
                "Algebraic Manipulation": {"weight": 0.35, "description": "Uses proper algebraic techniques and operations"},
                "Solution Accuracy": {"weight": 0.25, "description": "Arrives at correct numerical answers"},
                "Work Presentation": {"weight": 0.15, "description": "Shows clear, organized work with proper notation"}
            },
            "biology": {
                "Conceptual Understanding": {"weight": 0.35, "description": "Demonstrates mastery of biological concepts and theories"},
                "Scientific Reasoning": {"weight": 0.30, "description": "Applies biological principles to analyze and solve problems"},
                "Data Interpretation": {"weight": 0.20, "description": "Correctly interprets biological data and experimental results"},
                "Scientific Communication": {"weight": 0.15, "description": "Uses proper biological terminology and clear explanations"}
            },
            "calculus": {
                "Mathematical Concepts": {"weight": 0.30, "description": "Understanding of calculus principles (limits, derivatives, integrals)"},
                "Problem-Solving Strategy": {"weight": 0.25, "description": "Selects appropriate calculus techniques and methods"},
                "Computational Accuracy": {"weight": 0.25, "description": "Performs calculations correctly with proper steps"},
                "Mathematical Communication": {"weight": 0.20, "description": "Clear notation and logical progression of mathematical work"}
            },
            "chemistry": {
                "Conceptual Understanding": {"weight": 0.30, "description": "Mastery of chemical principles and theories"},
                "Problem Solving": {"weight": 0.30, "description": "Application of concepts to solve chemical problems"},
                "Quantitative Analysis": {"weight": 0.25, "description": "Accurate calculations and stoichiometry"},
                "Scientific Communication": {"weight": 0.15, "description": "Clear explanation of chemical reasoning"}
            },
            "engineering": {
                "Engineering Principles": {"weight": 0.30, "description": "Application of fundamental engineering concepts"},
                "Problem-Solving Approach": {"weight": 0.25, "description": "Systematic approach to engineering problems"},
                "Technical Analysis": {"weight": 0.25, "description": "Quantitative analysis and mathematical reasoning"},
                "Professional Communication": {"weight": 0.20, "description": "Clear technical documentation and presentation"}
            },
            "physics": {
                "Physics Concepts": {"weight": 0.30, "description": "Understanding of physical principles and laws"},
                "Mathematical Application": {"weight": 0.30, "description": "Correct use of equations and mathematical tools"},
                "Problem-Solving Strategy": {"weight": 0.30, "description": "Logical approach to physics problems"},
                "Units & Dimensional Analysis": {"weight": 0.10, "description": "Proper use of units and dimensional consistency"}
            },
            # Humanities
            "english_literature": {
                "essay": {
                    "Thesis Development": {"weight": 0.25, "description": "Clarity and insight of thesis statement"},
                    "Textual Evidence": {"weight": 0.30, "description": "Quality and analysis of evidence"},
                    "Literary Techniques": {"weight": 0.20, "description": "Understanding of literary devices"},
                    "Organization": {"weight": 0.15, "description": "Structure and flow of arguments"},
                    "Language": {"weight": 0.10, "description": "Writing quality and style"}
                },
                "creative_writing": {
                    "Originality": {"weight": 0.30, "description": "Creativity and uniqueness"},
                    "Character Development": {"weight": 0.25, "description": "Depth and believability"},
                    "Plot Structure": {"weight": 0.20, "description": "Narrative coherence"},
                    "Language Use": {"weight": 0.15, "description": "Stylistic choices"},
                    "Theme Exploration": {"weight": 0.10, "description": "Depth of thematic elements"}
                }
            },
            "history": {
                "research_paper": {
                    "Historical Argument": {"weight": 0.25, "description": "Clarity and validity of historical thesis"},
                    "Primary Source Analysis": {"weight": 0.25, "description": "Use and interpretation of primary sources"},
                    "Historical Context": {"weight": 0.20, "description": "Understanding of historical period"},
                    "Research Quality": {"weight": 0.20, "description": "Depth and breadth of research"},
                    "Historical Writing": {"weight": 0.10, "description": "Adherence to historical writing conventions"}
                },
                "document_analysis": {
                    "Source Interpretation": {"weight": 0.35, "description": "Analysis of source content"},
                    "Contextualization": {"weight": 0.25, "description": "Placement in historical context"},
                    "Bias Recognition": {"weight": 0.20, "description": "Identification of source perspective"},
                    "Argumentation": {"weight": 0.20, "description": "Development of historical argument"}
                }
            },
            # Social Sciences
            "psychology": {
                "research_report": {
                    "Literature Review": {"weight": 0.25, "description": "Comprehensiveness of research review"},
                    "Methodology": {"weight": 0.25, "description": "Appropriateness of research design"},
                    "Data Analysis": {"weight": 0.25, "description": "Accuracy of statistical methods"},
                    "Discussion": {"weight": 0.15, "description": "Interpretation of results"},
                    "APA Formatting": {"weight": 0.10, "description": "Adherence to APA guidelines"}
                },
                "case_study": {
                    "Case Analysis": {"weight": 0.35, "description": "Depth of case examination"},
                    "Theory Application": {"weight": 0.30, "description": "Use of psychological principles"},
                    "Diagnostic Reasoning": {"weight": 0.20, "description": "Clinical assessment quality"},
                    "Treatment Recommendations": {"weight": 0.15, "description": "Appropriate intervention strategies"}
                }
            },
            "economics": {
                "analysis_paper": {
                    "Theory Application": {"weight": 0.30, "description": "Use of economic principles"},
                    "Data Interpretation": {"weight": 0.25, "description": "Analysis of economic indicators"},
                    "Economic Reasoning": {"weight": 0.25, "description": "Logical economic argumentation"},
                    "Policy Implications": {"weight": 0.15, "description": "Practical application insights"},
                    "Technical Communication": {"weight": 0.05, "description": "Clarity of economic presentation"}
                },
                "data_interpretation": {
                    "Statistical Analysis": {"weight": 0.35, "description": "Accuracy of data processing"},
                    "Graphical Representation": {"weight": 0.25, "description": "Quality of data visualization"},
                    "Economic Insight": {"weight": 0.25, "description": "Interpretation of economic trends"},
                    "Conclusion Validity": {"weight": 0.15, "description": "Support for economic conclusions"}
                }
            },
            # Arts
            "music_theory": {
                "composition": {
                    "Harmonic Structure": {"weight": 0.30, "description": "Chord progression quality"},
                    "Melodic Development": {"weight": 0.25, "description": "Theme and variation technique"},
                    "Formal Design": {"weight": 0.20, "description": "Structural coherence"},
                    "Originality": {"weight": 0.15, "description": "Creative approach"},
                    "Notation Accuracy": {"weight": 0.10, "description": "Proper musical notation"}
                },
                "analysis": {
                    "Harmonic Analysis": {"weight": 0.30, "description": "Identification of chord functions"},
                    "Formal Recognition": {"weight": 0.25, "description": "Understanding of musical structure"},
                    "Historical Context": {"weight": 0.20, "description": "Placement in musical period"},
                    "Critical Interpretation": {"weight": 0.15, "description": "Insightful commentary"},
                    "Technical Terminology": {"weight": 0.10, "description": "Proper use of musical terms"}
                }
            },
            "visual_arts": {
                "portfolio": {
                    "Conceptual Development": {"weight": 0.25, "description": "Depth of artistic concept"},
                    "Technical Execution": {"weight": 0.25, "description": "Skill in medium application"},
                    "Creative Vision": {"weight": 0.20, "description": "Originality of approach"},
                    "Presentation Quality": {"weight": 0.20, "description": "Professional display"},
                    "Reflective Analysis": {"weight": 0.10, "description": "Artist statement quality"}
                },
                "critique": {
                    "Formal Analysis": {"weight": 0.30, "description": "Elements and principles evaluation"},
                    "Contextual Understanding": {"weight": 0.25, "description": "Historical/cultural placement"},
                    "Interpretive Depth": {"weight": 0.25, "description": "Meaning and significance analysis"},
                    "Critical Evaluation": {"weight": 0.20, "description": "Judgment of artistic merit"}
                }
            },
            # Language Arts
            "spanish": {
                "composition": {
                    "Language Accuracy": {"weight": 0.30, "description": "Grammar and syntax correctness"},
                    "Content Quality": {"weight": 0.25, "description": "Depth of ideas"},
                    "Cultural Relevance": {"weight": 0.20, "description": "Appropriate cultural references"},
                    "Vocabulary Range": {"weight": 0.15, "description": "Lexical diversity"},
                    "Task Completion": {"weight": 0.10, "description": "Addressing prompt requirements"}
                },
                "oral_presentation": {
                    "Pronunciation": {"weight": 0.30, "description": "Accuracy of speech sounds"},
                    "Fluency": {"weight": 0.25, "description": "Smoothness of delivery"},
                    "Content Organization": {"weight": 0.20, "description": "Logical structure"},
                    "Cultural Appropriateness": {"weight": 0.15, "description": "Contextual awareness"},
                    "Engagement": {"weight": 0.10, "description": "Audience connection"}
                }
            },
            "french": {
                "composition": {
                    "Language Accuracy": {"weight": 0.30, "description": "Grammar and syntax correctness"},
                    "Content Quality": {"weight": 0.25, "description": "Depth of ideas"},
                    "Cultural Relevance": {"weight": 0.20, "description": "Appropriate cultural references"},
                    "Vocabulary Range": {"weight": 0.15, "description": "Lexical diversity"},
                    "Task Completion": {"weight": 0.10, "description": "Addressing prompt requirements"}
                },
                "translation": {
                    "Accuracy": {"weight": 0.40, "description": "Faithfulness to source text"},
                    "Idiomatic Expression": {"weight": 0.25, "description": "Natural target language usage"},
                    "Cultural Adaptation": {"weight": 0.20, "description": "Appropriate cultural adjustments"},
                    "Terminology Consistency": {"weight": 0.15, "description": "Specialized term handling"}
                }
            }
        }

    def get_text_percentage(self, file_path: str) -> float:
        """
        Calculate the percentage of document that is covered by searchable text.
        If the returned percentage is very low, the document is likely scanned/handwritten.
        """
        try:
            total_page_area = 0.0
            total_text_area = 0.0

            doc = fitz.open(file_path)
            for page_num, page in enumerate(doc):
                total_page_area = total_page_area + abs(page.rect)
                text_area = 0.0
                for b in page.get_text("blocks"):
                    r = fitz.Rect(b[:4])  # rectangle where block text appears
                    text_area = text_area + abs(r)
                total_text_area = total_text_area + text_area
            doc.close()
            
            if total_page_area == 0:
                return 0.0
            return total_text_area / total_page_area
        except Exception as e:
            logger.warning(f"Error calculating text percentage: {str(e)}")
            return 0.5  # Default to middle ground if detection fails

    def is_handwritten_or_scanned(self, file_path: str) -> bool:
        """
        Enhanced detection: checks text coverage, garbled ratio, and valid word ratio.
        """
        text_percentage = self.get_text_percentage(file_path)
        logger.info(f"Text percentage for {os.path.basename(file_path)}: {text_percentage:.3f}")

        # Extract sample text for quality analysis
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            sample_text = ""
            for page in pdf_reader.pages[:2]:  # Check first 2 pages
                try:
                    page_text = page.extract_text()
                    if page_text:
                        sample_text += page_text[:500]
                except Exception as e:
                    logger.warning(f"Error extracting text from page: {e}")

            text_length = len(sample_text.strip())
            garbled_ratio = self._calculate_garbled_ratio(sample_text)
            valid_word_ratio = self._calculate_valid_word_ratio(sample_text)

            is_low_coverage = text_percentage < 0.12
            is_garbled = garbled_ratio > 0.2  # Lowered threshold
            is_sparse = text_length < 100 and len(pdf_reader.pages) > 0
            is_low_valid_word = valid_word_ratio < 0.5  # Less than 50% valid words

            should_use_ocr = is_low_coverage or is_garbled or is_sparse or is_low_valid_word

            logger.info(f"OCR Detection for {os.path.basename(file_path)}:")
            logger.info(f" Text coverage: {text_percentage:.3f}")
            logger.info(f" Garbled ratio: {garbled_ratio:.3f}")
            logger.info(f" Valid word ratio: {valid_word_ratio:.3f}")
            logger.info(f" Text length: {text_length}")
            logger.info(f" Decision: {'Use OCR' if should_use_ocr else 'Standard extraction'}")

            return should_use_ocr

        except Exception as e:
            logger.warning(f"Error in enhanced detection: {e}")
            return text_percentage < 0.01

    def _calculate_valid_word_ratio(self, text: str) -> float:
        """
        Returns the ratio of valid English words to total words in the text,
        using a fast set lookup (cloud-friendly, no dependencies).
        """
        words = re.findall(r'\b[a-zA-Z]{2,}\b', text)
        if not words:
            return 0.0
        valid = sum(1 for w in words if w.lower() in self.COMMON_ENGLISH_WORDS)
        return valid / len(words)

    def _calculate_garbled_ratio(self, text: str) -> float:
        """
        Calculate ratio of potentially garbled characters in text.
        Returns a value between 0.0 (clean text) and 1.0 (completely garbled).
        """
        if not text or len(text) < 10:
            return 1.0  # Very short or empty text should use OCR
    
        # Count suspicious patterns that indicate poor OCR
        garbled_indicators = 0
        total_chars = max(len(text), 1)  # Avoid division by zero
    
        # Look for patterns that indicate garbled text 
        # Excessive special characters
        special_char_matches = re.findall(r'[^\w\s\.\,\!\?\-\(\)\'\":;]', text)
        special_char_ratio = len(special_char_matches) / total_chars
        garbled_indicators += min(special_char_ratio * 5, 1.0)  # Weight: 5x
    
        # Weird character sequences (more than 3 consonants in a row)
        consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ]{4,}', text)
        consonant_cluster_ratio = len(consonant_clusters) / max(len(text.split()), 1)
        garbled_indicators += min(consonant_cluster_ratio * 3, 1.0)  # Weight: 3x
    
        # Single characters separated by spaces (common OCR error)
        isolated_chars = re.findall(r'\b[a-zA-Z]\b', text)
        isolated_ratio = len(isolated_chars) / max(len(text.split()), 1)
        garbled_indicators += min(isolated_ratio * 2, 1.0)  # Weight: 2x
    
        # Unusual character combinations (like w̅, multiple symbols, etc.)
        unusual_chars = re.findall(r'[\u0300-\u036f\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]', text)
        unusual_ratio = len(unusual_chars) / total_chars
        garbled_indicators += min(unusual_ratio * 10, 1.0)  # Weight: 10x
    
        # Final garbled ratio (normalized between 0 and 1)
        final_ratio = min(garbled_indicators / 4, 1.0)  # Divide by number of indicators
    
        return final_ratio


#    async def convert_pdf_to_images(self, file_path: str) -> List[str]:
#        """
#        Convert PDF pages to images for OCR processing.
#        """
#        try:
#            with tempfile.TemporaryDirectory() as temp_dir:
#                # Convert PDF to images
#                poppler_path = get_poppler_path()
#                if poppler_path:
#                    images = convert_from_path(file_path, dpi=300, fmt='jpeg', poppler_path=poppler_path)
#                else:
#                    images = convert_from_path(file_path, dpi=300, fmt='jpeg')
#                image_paths = []
#                
#                for i, image in enumerate(images):
#                    image_path = os.path.join(temp_dir, f"page_{i+1}.jpg")
#                    image.save(image_path, 'JPEG', quality=95)
#                    
#                    # Copy to permanent location for OCR processing
#                    permanent_path = file_path.replace('.pdf', f'_page_{i+1}.jpg')
#                    shutil.copy2(image_path, permanent_path)
#                    image_paths.append(permanent_path)
#                
#                logger.info(f"✓ Converted {len(images)} pages to images")
#                return image_paths
#        except Exception as e:
#            logger.error(f"Error converting PDF to images: {str(e)}")
#            return []

    async def call_handwriting_ocr_api(self, file_path: str) -> str:
        """
        Call the Handwriting OCR API to process a complete PDF document.
        Follows the official API documentation at https://www.handwritingocr.com/api/docs
        """
        if not self.handwriting_ocr_key or not self.handwriting_ocr_url:
            logger.warning("Handwriting OCR API credentials not configured")
            return ""

        try:
            # Step 1: Upload the entire PDF document
            headers = {
                'Authorization': f'Bearer {self.handwriting_ocr_key}',
                'Accept': 'application/json'
            }
        
            data = {
                'action': 'transcribe',
                'delete_after': '604800'  # Auto-delete after 7 days
            }
        
            with open(file_path, 'rb') as pdf_file:
                files = {'file': pdf_file}
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        'https://www.handwritingocr.com/api/v3/documents',
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60
                    )
                )
        
            if response.status_code in [200, 201]:
                result = response.json()
                document_id = result.get('id')
                if document_id:
                    logger.info(f"✓ Document uploaded successfully, ID: {document_id}")
                    # Step 2 & 3: Poll for completion and get results
                    return await self.poll_ocr_completion(document_id)
                else:
                    logger.error("No document ID returned from OCR API")
                    return ""
            else:
                logger.error(f"OCR API upload error: {response.status_code} - {response.text}")
                return ""
            
        except Exception as e:
            logger.error(f"Error calling handwriting OCR API: {str(e)}")
            return ""

    async def poll_ocr_completion(self, document_id: str, max_attempts: int = 60, delay: int = 10) -> str:
        """
        Poll the OCR API for document processing completion.
        Follows the official polling pattern from the API documentation.
        """
        headers = {
            'Authorization': f'Bearer {self.handwriting_ocr_key}',
            'Accept': 'application/json'
        }
    
        for attempt in range(max_attempts):
            try:
                # Use the correct polling endpoint from API docs
                status_url = f"https://www.handwritingocr.com/api/v3/documents/{document_id}"
            
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(status_url, headers=headers, timeout=30)
                )
            
                if response.status_code == 200:
                    # Check for empty response
                    if not response.content or not response.content.strip():
                        logger.error(f"OCR API returned empty response for document {document_id} (attempt {attempt+1})")
                        await asyncio.sleep(delay)
                        continue

                    # Parse JSON response
                    try:
                        result = response.json()
                    except json.JSONDecodeError:
                        logger.error(f"OCR API returned non-JSON response for document {document_id}: {response.status_code} - {response.text[:200]}")
                        await asyncio.sleep(delay)
                        continue

                    status = result.get('status', '')
                
                    if status == 'processed':
                        logger.info(f"✓ OCR processing completed for document {document_id}")
                        return self.extract_text_from_ocr_result(result)
                    elif status == 'failed':
                        logger.error(f"OCR processing failed for document {document_id}")
                        return ""
                    elif status in ['new', 'queued', 'processing']:
                        logger.info(f"OCR still processing document {document_id}, status: {status} (attempt {attempt + 1}/{max_attempts})")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.warning(f"Unknown OCR status '{status}' for document {document_id}")
                        await asyncio.sleep(delay)
                        continue
                else:
                    logger.error(f"Error checking OCR status: {response.status_code} - {response.text[:200]}")
                    await asyncio.sleep(delay)
                    continue
                
            except Exception as e:
                logger.error(f"Error polling OCR completion: {str(e)}")
                await asyncio.sleep(delay)
                continue
    
        logger.error(f"OCR polling timeout for document {document_id} after {max_attempts} attempts")
        return ""

    def extract_text_from_ocr_result(self, result: dict) -> str:
        """
        Extract text from OCR API result following the documented response format.
        The API returns results as an array of page objects with page_number and transcript.
        """
        try:
            if 'results' in result:
                # Multi-page format as documented in API docs
                all_text = ""
                for page_result in result['results']:
                    page_num = page_result.get('page_number', 1)
                    transcript = page_result.get('transcript', '')
                    if transcript.strip():
                        all_text += f"\n--- Page {page_num} (OCR) ---\n{transcript.strip()}\n"
                
                if all_text.strip():
                    logger.info(f"✓ OCR extracted text from {len(result['results'])} pages")
                    return all_text.strip()
                else:
                    logger.warning("OCR completed but no text was extracted")
                    return "OCR processing completed but no text was extracted"
            
            # Handle direct API response format (from your attached files)
            elif 'documents' in result:
                all_text = ""
                for doc in result['documents']:
                    if 'data' in doc:
                        for page_data in doc['data']:
                            page_num = page_data.get('page_number', 1)
                            content = page_data.get('content', '')
                            if content.strip():
                                # Clean up the OCR content for better readability
                                cleaned_content = self._clean_ocr_content(content)
                                all_text += f"\n--- Page {page_num} (OCR) ---\n{cleaned_content}\n"
                
                if all_text.strip():
                    logger.info(f"✓ OCR extracted text from document")
                    return all_text.strip()
                else:
                    logger.warning("OCR completed but no text was extracted")
                    return "OCR processing completed but no text was extracted"
            else:
                logger.warning(f"Unexpected OCR result format: {result}")
                return str(result)
                
        except Exception as e:
            logger.error(f"Error extracting text from OCR result: {str(e)}")
            return ""

    def _clean_ocr_content(self, content: str) -> str:
        """
        Clean and format OCR content for better AI grader readability.
        """
        # Remove excessive unicode characters and formatting
        content = content.replace('\u2081', '1').replace('\u2082', '2')
        content = content.replace('\u207b', '-').replace('\u2076', '6')
        content = content.replace('\u2079', '9').replace('\u00b2', '^2')
        content = content.replace('\u00b5', 'µ')
        
        # Add line breaks for better structure
        content = content.replace('. ', '.\n')
        content = content.replace('? ', '?\n')
        content = content.replace(': ', ':\n')
        
        # Clean up multiple newlines
        content = re.sub(r'\n\s*\n', '\n\n', content)
        
        return content.strip()

    async def extract_text_with_ocr_fallback(self, file_path: str) -> str:
        """
        Extract text from PDF with OCR fallback for handwritten/scanned documents.
        This is the main entry point that decides whether to use standard extraction or OCR.
        """
        # First, try standard text extraction
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            text_content = ""
        
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        text_content += f"\n--- Page {page_num + 1} ---\n{page_text}"
                except Exception as page_error:
                    logger.warning(f"Could not extract text from page {page_num + 1}: {str(page_error)}")

            # Check if we got meaningful text using your existing detection logic
            if text_content.strip() and not self.is_handwritten_or_scanned(file_path):
                logger.info(f"✓ Standard text extraction successful for {os.path.basename(file_path)}")
                return text_content.strip()
            else:
                print(f"⚠️ FALLBACK TO OCR: {os.path.basename(file_path)}")  # Temporary debug
                logger.info(f"⚠️ Low text quality detected, falling back to OCR for {os.path.basename(file_path)}")
      
        except Exception as e:
            logger.warning(f"Standard text extraction failed: {str(e)}, falling back to OCR")

        # Fallback to OCR processing - send entire PDF to API (no looping!)
        try:
            ocr_text = await self.call_handwriting_ocr_api(file_path)
        
            if ocr_text.strip():
                logger.info(f"✓ OCR extraction successful for {os.path.basename(file_path)}")
                return ocr_text.strip()
            else:
                return f"OCR processing completed for {os.path.basename(file_path)} but no text was extracted"
            
        except Exception as e:
            logger.error(f"OCR fallback failed: {str(e)}")
            return f"Error processing {os.path.basename(file_path)}: {str(e)}"
    
    def extract_student_name(self, file_path: str) -> str:
        try:
            filename = os.path.basename(file_path)
            name = filename.replace('.pdf', '').replace('submission_', '').replace('_', ' ')
            name = re.sub(r'^\d+\s*', '', name)
            return name.strip() if name.strip() else "Unknown Student"
        except:
            return "Unknown Student"

    async def extract_text_from_pdf(self, file_path: str) -> str:
        """
        Main text extraction method with OCR integration.
        """
        return await self.extract_text_with_ocr_fallback(file_path)

    async def generate_pdf_report(self, student_name: str, result: dict,
                                 rubric: dict, subject: str,
                                 assessment_type: str, output_path: str):
        try:
            pdf = PDFReport()
            
            # Student-facing header
            pdf.chapter_title(f"Dear {student_name},")
            pdf.chapter_body(f"Here is your feedback for the {subject.title()} {assessment_type.replace('_', ' ').title()} assignment completed on {datetime.now().strftime('%B %d, %Y')}.")
            pdf.ln(5)
            
            # Overall score section with enhanced styling
            font_family = 'Arial' if hasattr(pdf, '_use_builtin_fonts') and pdf._use_builtin_fonts else 'DejaVu'
            pdf.set_font(font_family, 'B', 16)
            
            # Score-based background color
            score = result['overall_score']
            if score >= 90:
                pdf.set_fill_color(220, 252, 231)  # Light green
                pdf.set_text_color(22, 101, 52)    # Dark green
            elif score >= 80:
                pdf.set_fill_color(254, 249, 195)  # Light yellow
                pdf.set_text_color(133, 77, 14)    # Dark yellow
            elif score >= 70:
                pdf.set_fill_color(255, 237, 213)  # Light orange
                pdf.set_text_color(154, 52, 18)    # Dark orange
            else:
                pdf.set_fill_color(254, 226, 226)  # Light red
                pdf.set_text_color(153, 27, 27)    # Dark red
                
            pdf.cell(0, 12, f"Your Overall Score: {score}%", 1, 1, 'C', 1)
            pdf.set_text_color(0, 0, 0)  # Reset to black
            pdf.ln(5)
            
            # Grade interpretation - student-facing
            if score >= 90:
                grade_letter = "A"
                interpretation = "Excellent work! You've demonstrated outstanding understanding."
            elif score >= 80:
                grade_letter = "B"
                interpretation = "Good work! You show solid understanding of the concepts."
            elif score >= 70:
                grade_letter = "C"
                interpretation = "Satisfactory work. You have a basic understanding with room for improvement."
            elif score >= 60:
                grade_letter = "D"
                interpretation = "Your work shows some understanding, but needs significant improvement."
            else:
                grade_letter = "F"
                interpretation = "Your work indicates you need additional support with these concepts."
            
            # Add note if OCR was used - student-facing
            if "(OCR)" in result.get('detailed_feedback', ''):
                pdf.set_font(font_family, 'I', 10)
                pdf.chapter_body("Note: Your handwritten submission was processed using advanced text recognition technology. If any feedback seems unclear, please discuss it with your instructor.")
                pdf.ln(3)
            
            pdf.set_font(font_family, 'B', 14)
            pdf.chapter_title(f"Your Letter Grade: {grade_letter}")
            pdf.set_font(font_family, '', 12)
            pdf.chapter_body(interpretation)
            pdf.ln(5)
            
            # Rubric breakdown - student-facing with enhanced styling
            pdf.set_font(font_family, 'B', 14)
            pdf.chapter_title("Your Detailed Score Breakdown:")
            pdf.set_font(font_family, '', 11)
            pdf.chapter_body("Here's how you performed in each area:")
            pdf.ln(3)
            
            for criterion, score_val in result['rubric_scores'].items():
                weight = rubric[criterion]['weight']
                description = rubric[criterion]['description']
                pdf.add_score_section(f"{criterion} ({weight*100:.0f}%)", score_val)
                pdf.set_font(font_family, 'I', 10)
                pdf.cell(0, 5, f"  {description}", 0, 1, 'L')
                pdf.ln(2)
            
            pdf.ln(5)
            
            # Feedback sections - student-facing
            if result.get('feedback'):
                pdf.set_font(font_family, 'B', 14)
                pdf.chapter_title("Overall Feedback:")
                pdf.set_font(font_family, '', 11)
                pdf.chapter_body(result['feedback'])
            
            if result.get('strengths'):
                pdf.set_font(font_family, 'B', 14)
                pdf.chapter_title("What You Did Well:")
                pdf.set_font(font_family, '', 11)
                for strength in result['strengths']:
                    # Ensure student-facing language
                    if not strength.lower().startswith(('you ', 'your ')):
                        strength = f"You {strength.lower()}"
                    pdf.chapter_body(f"• {strength}")
            
            if result.get('areas_for_improvement'):
                pdf.set_font(font_family, 'B', 14)
                pdf.chapter_title("Areas for Growth:")
                pdf.set_font(font_family, '', 11)
                for improvement in result['areas_for_improvement']:
                    # Ensure student-facing language
                    if not improvement.lower().startswith(('you ', 'your ', 'consider ', 'try ')):
                        improvement = f"You can work on {improvement.lower()}"
                    pdf.chapter_body(f"• {improvement}")
            
            if result.get('detailed_feedback'):
                pdf.set_font(font_family, 'B', 14)
                pdf.chapter_title("Detailed Analysis:")
                pdf.set_font(font_family, '', 11)
                pdf.chapter_body(result['detailed_feedback'])
            
            # Professional footer with logo branding
            pdf.create_professional_footer()
            
            # Save report
            pdf.output(output_path)
            logger.info(f"✓ Student-facing PDF report with logo generated: {output_path}")
            
        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}")
            print(f"✗ Error generating PDF report: {str(e)}")
            raise

    async def create_reports_zip(self, task_dir: Path) -> str:
        try:
            reports_dir = task_dir / "reports"
            if not reports_dir.exists():
                logger.warning(f"No reports directory found at {reports_dir}")
                return ""
            
            zip_path = task_dir / "all_reports.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for report_file in reports_dir.glob("*.pdf"):
                    zipf.write(report_file, report_file.name)
            
            logger.info(f"✓ Created reports ZIP: {zip_path}")
            return str(zip_path)
        except Exception as e:
            logger.error(f"Error creating reports ZIP: {str(e)}")
            return ""

    async def grade_assignment(self, task_data: Dict) -> Dict:
        try:
            task_id = task_data["task_id"]
            subject = task_data["subject"]
            assessment_type = task_data["assessment_type"]
            files = task_data["files"]

            logger.info(f"🎯 Starting grading for task {task_id}")

            task_dir = Path(f"uploads/{task_id}")
            reports_dir = task_dir / "reports"
            reports_dir.mkdir(exist_ok=True)

            assignment_text = ""
            if "assignment" in files:
                assignment_text = await self.extract_text_from_pdf(files["assignment"])

            solution_text = ""
            if "solution" in files:
                solution_text = await self.extract_text_from_pdf(files["solution"])

            # Get appropriate rubric
            rubric = self.get_appropriate_rubric(subject, assessment_type)

            submission_results = []
            submissions = files.get("submissions", [])

            for i, submission_path in enumerate(submissions):
                student_name = self.extract_student_name(submission_path)
                submission_text = await self.extract_text_from_pdf(submission_path)

                individual_result = await self.grade_individual_submission(
                    assignment_text=assignment_text,
                    submission_text=submission_text,
                    solution_text=solution_text,
                    rubric=rubric,
                    subject=subject,
                    assessment_type=assessment_type
                )

                individual_result["submission_id"] = i + 1
                individual_result["file_path"] = submission_path
                individual_result["student_name"] = student_name
                submission_results.append(individual_result)

                report_filename = f"{student_name.replace(' ', '_')}_report.pdf"
                report_path = reports_dir / report_filename

                await self.generate_pdf_report(
                    student_name=student_name,
                    result=individual_result,
                    rubric=rubric,
                    subject=subject,
                    assessment_type=assessment_type,
                    output_path=str(report_path)
                )

            zip_path = await self.create_reports_zip(task_dir)
            overall_stats = self.calculate_overall_statistics(submission_results)

            results = {
                "task_id": task_id,
                "subject": subject,
                "assessment_type": assessment_type,
                "rubric_used": rubric,
                "submission_count": len(submissions),
                "individual_results": submission_results,
                "overall_statistics": overall_stats,
                "reports_zip_path": zip_path,
                "processed_at": datetime.now().isoformat(),
                "status": "completed"
            }

            logger.info(f"🎉 Grading completed for {task_id}")
            return results

        except Exception as e:
            logger.error(f"✗ Grading error for {task_data.get('task_id', 'unknown')}: {str(e)}")
            return {
                "task_id": task_data.get("task_id", "unknown"),
                "status": "error",
                "error": str(e),
                "processed_at": datetime.now().isoformat()
            }

    def get_appropriate_rubric(self, subject: str, assessment_type: str) -> Dict:
        """
        Get the appropriate rubric for a subject and assessment type.
        Handles both direct subject rubrics and nested subject[assessment_type] rubrics.
        """
        if subject not in self.default_rubrics:
            return self._get_fallback_rubric(subject, assessment_type)
    
        subject_rubrics = self.default_rubrics[subject]
    
        # Check if this is a nested structure (has assessment_type keys)
        if assessment_type in subject_rubrics:
            # Nested structure: subject -> assessment_type -> rubric
            return subject_rubrics[assessment_type]
    
        # Check if this is a direct rubric structure
        # (Direct rubrics have criteria with 'weight' and 'description' keys)
        first_key = next(iter(subject_rubrics.keys()), None)
        if first_key and isinstance(subject_rubrics[first_key], dict) and 'weight' in subject_rubrics[first_key]:
            # This is a direct rubric - use it regardless of assessment_type
            return subject_rubrics
    
        # If we can't determine the structure, use fallback
        return self._get_fallback_rubric(subject, assessment_type)
    
    def _get_fallback_rubric(self, subject: str, assessment_type: str) -> Dict:
        # Fallback logic for unconfigured combinations
        return {
            "Content Quality": {"weight": 0.40, "description": "Relevance and depth of content"},
            "Technical Accuracy": {"weight": 0.40, "description": "Correctness of information"},
            "Organization": {"weight": 0.15, "description": "Logical structure and flow"},
            "Presentation": {"weight": 0.05, "description": "Clarity and professionalism"}
        }
    
    async def grade_individual_submission(self, assignment_text: str, submission_text: str,
                                        solution_text: str, rubric: Dict, subject: str, 
                                        assessment_type: str) -> Dict:
        prompt = self.create_grading_prompt(
            assignment_text, submission_text, solution_text, rubric, subject, assessment_type)
        
        try:
            response = await self.call_perplexity_api(prompt)
            ai_feedback = self.parse_ai_response(response)
            
            rubric_scores = {}
            total_weighted_score = 0
            for criterion, details in rubric.items():
                score = ai_feedback.get("scores", {}).get(criterion, 75)
                rubric_scores[criterion] = score
                total_weighted_score += score * details["weight"]
            
            result = {
                "overall_score": round(total_weighted_score),
                "rubric_scores": rubric_scores,
                "feedback": ai_feedback.get("feedback", "Good work overall."),
                "detailed_feedback": ai_feedback.get("detailed_feedback", ""),
                "strengths": ai_feedback.get("strengths", []),
                "areas_for_improvement": ai_feedback.get("improvements", []),
                "ai_confidence": ai_feedback.get("confidence", 0.8)
            }
            
            logger.info(f"✓ AI grading completed: {result['overall_score']}%")
            return result
        except Exception as e:
            logger.warning(f"⚠️ AI grading failed, using fallback: {str(e)}")
            return {
                "overall_score": 75,
                "rubric_scores": {k: 75 for k in rubric.keys()},
                "feedback": f"Automated grading completed. Manual review recommended. (AI Error: {str(e)[:100]})",
                "detailed_feedback": "The submission has been processed with basic scoring due to AI service issues.",
                "strengths": ["Submission received and processed"],
                "areas_for_improvement": ["Manual review recommended for detailed feedback"],
                "ai_confidence": 0.5
            }
    
    def create_grading_prompt(self, assignment_text: str, submission_text: str,
                             solution_text: str, rubric: Dict, subject: str,
                             assessment_type: str) -> str:
        rubric_text = "\n".join([
            f"- {criterion} ({details['weight']*100:.0f}%): {details['description']}"
            for criterion, details in rubric.items()
        ])

        # Add note about OCR processing if detected
        ocr_note = ""
        if "(OCR)" in submission_text:
            ocr_note = "\nNote: This submission was processed using OCR technology from handwritten content. Please account for potential OCR errors in your evaluation."

        prompt = f"""
You are an expert {subject} educator providing feedback directly to a student on their {assessment_type.replace('_', ' ')} assignment.

SCORING SCALE GUIDELINES:
- 90-100: Excellent work with correct answers and clear understanding
- 80-89: Good work with mostly correct answers and solid understanding  
- 70-79: Satisfactory work with adequate understanding, some errors
- 60-69: Below expectations with significant errors or misunderstanding
- Below 60: Major problems with fundamental misunderstanding

IMPORTANT: If a student demonstrates correct understanding, gets most answers right, and shows their work clearly, assign scores in the 85-95 range. Only use scores below 70 for work with fundamental errors or major misunderstandings.

ASSIGNMENT INSTRUCTIONS:
{assignment_text[:2000]}

GRADING RUBRIC:
{rubric_text}

STUDENT SUBMISSION:
{submission_text[:3000]}

{f"SOLUTION/ANSWER KEY: {solution_text[:1000]}" if solution_text else ""}

Please provide feedback DIRECTLY TO THE STUDENT using "you" and "your" language:

1. A score (0-100) for each rubric criterion using the scale above
2. Overall constructive feedback addressed to the student
3. Specific strengths you identified in their work
4. Areas where they can improve
5. Detailed comments about their work

IMPORTANT: Write all feedback as if you are speaking directly to the student. Use "you," "your work," "you demonstrated," etc. Be encouraging and supportive while providing constructive guidance.

Format your response as JSON with the following structure:
{{
"scores": {{
"criterion_name": score_number,
...
}},
"feedback": "Overall feedback summary addressed directly to the student",
"detailed_feedback": "Detailed analysis written directly to the student",
"strengths": ["Your strength 1", "Your strength 2", ...],
"improvements": ["You can improve by...", "Consider working on...", ...],
"confidence": 0.0-1.0
}}

Be encouraging and supportive in your feedback. Address the student directly and help them understand what they did well and how they can continue to grow in {subject}.{ocr_note}
"""
        return prompt

    async def call_perplexity_api(self, prompt: str) -> Dict:
        if not self.api_key:
            raise Exception("Perplexity API key not configured")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert educator providing fair, detailed, and constructive feedback on student work. Be generous and supportive in your scoring, focusing on rewarding correct reasoning and effort. Only deduct points for major errors."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.3
        }
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(self.api_url, headers=headers, json=data, timeout=60)
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"API error: {response.status_code} - {response.text}")
    
    def parse_ai_response(self, response: Dict) -> Dict:
        try:
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
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
