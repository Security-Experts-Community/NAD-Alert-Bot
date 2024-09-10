#!/usr/bin/env bash

set -euo pipefail

# Default values
PYTHON_TYPE="system"
CUSTOM_PYTHON_PATH=""
VENV_NAME="bot-venv"
CREATE_SERVICE=false
GENERATE_TLS_KEYS=false
TLS_CN="localhost"

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -p, --python TYPE    Specify Python type: system, custom, or nad (default: system)"
    echo "  -c, --custom-path    Path to custom Python (required if --python custom)"
    echo "  -v, --venv-name      Name of the virtual environment (default: bot-venv)"
    echo "  -s, --create-service Create systemd service for the bot"
    echo "  -t, --tls            Generate TLS keys using OpenSSL"
    echo "  --cn NAME            Specify Common Name (CN) for TLS certificate (default: localhost)"
    echo "  -h, --help           Display this help message"
}

display_info() {
    echo "Running bot environment setup with default settings:"
    echo "- Using system Python"
    echo "- Creating virtual environment named '$VENV_NAME'"
    echo "- Not creating systemd service"
    echo "- Not generating TLS keys"
    echo ""
    echo "To customize these settings, run the script with --help to see available options."
    echo ""
}

if [ $# -eq 0 ]; then
    display_info
else
    while [[ $# -gt 0 ]]; do
        case $1 in
            -p|--python)
                PYTHON_TYPE="$2"
                shift 2
                ;;
            -c|--custom-path)
                CUSTOM_PYTHON_PATH="$2"
                shift 2
                ;;
            -v|--venv-name)
                VENV_NAME="$2"
                shift 2
                ;;
            -s|--create-service)
                CREATE_SERVICE=true
                shift
                ;;
            -t|--tls)
                GENERATE_TLS_KEYS=true
                shift
                ;;
            --cn)
                TLS_CN="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
fi

check_python_version() {
    local python_path="$1"
    local min_version="3.9"
    local python_version

    python_version=$("$python_path" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

    if [ "$(printf '%s\n' "$min_version" "$python_version" | sort -V | head -n1)" = "$min_version" ]; then
        echo "Python version $python_version meets the minimum requirement of $min_version"
    else
        echo "Error: Python version $python_version does not meet the minimum requirement of $min_version"
        exit 1
    fi
}

check_pip() {
    local python_path="$1"
    if ! "$python_path" -m pip --version &> /dev/null; then
        echo "Error: pip is not installed for the selected Python version."
        echo "To install pip, try one of the following methods:"
        echo "1. Use your system's package manager. For example:"
        echo "   - On Ubuntu/Debian/Astra Linux: sudo apt-get install python3-pip"
        echo "   - On CentOS/RHEL: sudo yum install python3-pip"
        echo "   - On macOS with Homebrew: brew install python (includes pip)"
        echo "2. Use the get-pip.py script:"
        echo "   curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py"
        echo "   $python_path get-pip.py"
        echo "After installing pip, please run this script again."
        exit 1
    fi
}

generate_tls_keys() {
    if ! command -v openssl &> /dev/null; then
        echo "Error: OpenSSL is not installed or not in the PATH"
        exit 1
    fi

    echo "Generating TLS keys with CN: $TLS_CN"
    openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365 -subj "/CN=$TLS_CN"
    echo "TLS keys generated: cert.pem and key.pem"
}

echo "Setting up bot environment..."

# Determine Python path based on the specified type
case $PYTHON_TYPE in
    system)
        PYTHON_PATH=$(command -v python3)
        if [ -z "$PYTHON_PATH" ]; then
            echo "Error: System Python 3 not found"
            exit 1
        fi
        ;;
    custom)
        if [ -z "$CUSTOM_PYTHON_PATH" ]; then
            echo "Error: Custom Python path not provided. Use -c or --custom-path to specify."
            exit 1
        fi
        PYTHON_PATH="$CUSTOM_PYTHON_PATH"
        ;;
    nad)
        PYTHON_PATH="/opt/ptsecurity/ptnad-python/bin/python3"
        ;;
    *)
        echo "Error: Invalid Python type specified"
        usage
        exit 1
        ;;
esac

echo "Using Python at: $PYTHON_PATH"

# Check if the Python path exists
if [ ! -f "$PYTHON_PATH" ]; then
    echo "Error: Python not found at $PYTHON_PATH"
    exit 1
fi

# Check Python version
check_python_version "$PYTHON_PATH"

# Check if pip is installed
check_pip "$PYTHON_PATH"

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo "Error: requirements.txt not found in the current directory"
    exit 1
fi

echo "Creating virtual environment: $VENV_NAME"
"$PYTHON_PATH" -m venv "$VENV_NAME"
source "$VENV_NAME/bin/activate"

echo "Installing dependencies from requirements.txt"
pip install -r requirements.txt

echo "Virtual environment created and dependencies installed successfully"

# Create systemd service if requested
if [ "$CREATE_SERVICE" = true ]; then
    echo "Creating systemd service..."
    BOT_DIR=$(pwd)
    MAIN_SCRIPT="$BOT_DIR/main.py"
    SERVICE_NAME="nad_alert_bot"
    SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

    if [ ! -f "$MAIN_SCRIPT" ]; then
        echo "Error: main.py not found in the current directory"
        exit 1
    fi

    # Create systemd service file
    cat << EOF | sudo tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=NAD Alert Bot
After=network.target

[Service]
ExecStart=$BOT_DIR/$VENV_NAME/bin/python $MAIN_SCRIPT
WorkingDirectory=$BOT_DIR
Restart=always
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF

    echo "Systemd service created: $SERVICE_FILE"
    echo "To start the service, run: sudo systemctl start $SERVICE_NAME"
    echo "To enable the service on boot, run: sudo systemctl enable $SERVICE_NAME"
else
    echo "Skipping systemd service creation (use -s or --create-service to create it)"
fi

# Generate TLS keys if requested
if [ "$GENERATE_TLS_KEYS" = true ]; then
    echo "Generating TLS keys..."
    generate_tls_keys
else
    echo "Skipping TLS key generation (use -t or --tls to generate keys)"
fi

echo "Bot environment setup complete"
