"""
Setup script for OAuth-enabled Claude API Token Usage Demo
Helps verify dependencies and configuration
"""

import sys
import os

def check_python_version():
    """Check if Python version is 3.7+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print("❌ Python 3.7+ is required")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True

def check_dependencies():
    """Check if required packages are installed"""
    required = [
        'flask',
        'flask_cors',
        'requests',
        'flask_session',
        'requests_oauthlib'
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - NOT INSTALLED")
            missing.append(package)
    
    return len(missing) == 0, missing

def check_env_file():
    """Check if .env file exists and has required variables"""
    if not os.path.exists('.env'):
        print("ℹ️  .env file not found (optional)")
        print("   You can use system environment variables instead")
        print("   Or create .env from .env.example for local development")
        return True  # Not an error - env vars can be set elsewhere
    
    print("✅ .env file exists")
    
    # Check for recommended OAuth variables
    recommended_vars = [
        'SECRET_KEY',
        'POPDOCK_OAUTH_CLIENT_ID',
        'OAUTH_REDIRECT_URI'
    ]
    
    with open('.env', 'r') as f:
        content = f.read()
    
    configured = []
    for var in recommended_vars:
        if var in content and f"{var}=your-" not in content:
            configured.append(var)
            print(f"   ✅ {var}")
        else:
            print(f"   ℹ️  {var} (optional)")
    
    if len(configured) == 0:
        print("   ℹ️  No OAuth variables configured - OAuth will be disabled")
    
    return True

def create_directories():
    """Create required directories"""
    dirs = ['logs', 'flask_session']
    for dir_name in dirs:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
            print(f"✅ Created {dir_name}/ directory")
        else:
            print(f"✅ {dir_name}/ directory exists")

def main():
    print("=" * 60)
    print("Claude API Token Usage Demo - OAuth Setup Verification")
    print("=" * 60)
    print()
    
    print("📋 Checking Python Version...")
    python_ok = check_python_version()
    print()
    
    print("📦 Checking Dependencies...")
    deps_ok, missing = check_dependencies()
    print()
    
    if not deps_ok:
        print("💡 To install missing packages, run:")
        print("   pip install -r requirements.txt")
        print()
    
    print("⚙️  Checking Configuration...")
    env_ok = check_env_file()
    print()
    
    print("📁 Checking/Creating Directories...")
    create_directories()
    print()
    
    print("=" * 60)
    if python_ok and deps_ok:
        print("✅ Setup Complete! Ready to run the application.")
        print()
        print("To start the server:")
        print("   python app.py")
        print()
        print("Then open your browser to:")
        print("   http://localhost:5000")
        print()
        if not env_ok:
            print("ℹ️  OAuth Not Configured:")
            print("   - OAuth features will be disabled")
            print("   - You can still use token-based MCP authentication")
            print("   - To enable OAuth, set environment variables or create .env")
    else:
        print("⚠️  Setup Incomplete - Please fix the issues above")
    print("=" * 60)

if __name__ == '__main__':
    main()
