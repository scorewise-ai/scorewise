#!/bin/bash
# ScoreWise AI Deployment Script
# Place this file as deploy.sh in the root directory of your project
# Make it executable with: chmod +x deploy.sh

echo "🚀 ScoreWise AI Deployment Script"
echo "=================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip first."
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "📚 Installing requirements..."
pip install -r requirements.txt

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p uploads
mkdir -p static/css
mkdir -p static/js
mkdir -p templates

# Copy environment template if .env doesn't exist
if [ ! -f .env ]; then
    echo "🔧 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your actual API keys and configuration!"
fi

# Check if all required templates exist
echo "🔍 Checking template files..."
required_templates=("index.html" "pricing.html" "uploadfile.html" "dashboard.html" "success.html")

for template in "${required_templates[@]}"; do
    if [ ! -f "templates/$template" ]; then
        echo "⚠️  Missing template: templates/$template"
    else
        echo "✅ Found: templates/$template"
    fi
done

# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo "❌ main.py not found! Please ensure main.py is in the root directory."
    exit 1
else
    echo "✅ Found: main.py"
fi

# Check if grader.py exists
if [ ! -f "grader.py" ]; then
    echo "❌ grader.py not found! Please ensure grader.py is in the root directory."
    exit 1
else
    echo "✅ Found: grader.py"
fi

echo ""
echo "🎉 Deployment setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit your .env file with actual API keys:"
echo "   - STRIPE_SECRET_KEY"
echo "   - STRIPE_PUBLISHABLE_KEY" 
echo "   - PERPLEXITY_API_KEY"
echo "   - STRIPE_WEBHOOK_SECRET"
echo "   - PRICE_ID_STANDARD, PRICE_ID_PRO, PRICE_ID_ENTERPRISE"
echo ""
echo "2. To run locally:"
echo "   source venv/bin/activate"
echo "   uvicorn main:app --reload"
echo ""
echo "3. For Render deployment:"
echo "   - Connect your GitHub repository"
echo "   - Set build command: pip install -r requirements.txt"
echo "   - Set start command: uvicorn main:app --host 0.0.0.0 --port \$PORT"
echo "   - Add environment variables in Render dashboard"
echo ""
echo "4. Configure Stripe webhooks:"
echo "   - Add webhook endpoint: https://your-app.onrender.com/webhook"
echo "   - Select events: checkout.session.completed, invoice.paid"
echo ""
echo "🔒 Security checklist:"
echo "- Never commit .env file to version control"
echo "- Use strong SECRET_KEY"
echo "- Set up proper CORS origins for production"
echo "- Enable HTTPS in production"
echo ""
echo "Happy grading! 🎓"