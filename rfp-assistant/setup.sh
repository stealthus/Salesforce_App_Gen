#!/bin/bash
# Setup script for RFP Response Assistant

# Create virtual environment
echo "Creating virtual environment..."
python -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create knowledge base directory
echo "Creating knowledge base directory..."
mkdir -p data/knowledge_base

echo "Setup complete! Run the application with: uvicorn app:app --reload"
