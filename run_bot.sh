#!/bin/bash
# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo "Error: main.py not found in the current directory"
    exit 1
fi

VENV_NAME="bot-venv"
if [ ! -d "$VENV_NAME" ]; then
    echo "Error: Virtual environment not found. Please run the setup_env script first."
    exit 1
fi

source $VENV_NAME/bin/activate
python main.py
deactivate
