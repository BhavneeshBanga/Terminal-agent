# 🚀 BhavAI — Personal Terminal AI Agent - Project Overview & Documentation Plan

## 📋 Project Summary

**BhavAI** is a production-ready, lightweight, personal terminal AI agent powered exclusively by the **Sarvam-105B LLM API**. It operates directly within your current working directory, following a robust **Reason → Act → Observe** (ReAct) loop to solve complex tasks.

## 🏗️ Architecture Overview

### Core Components

1. **CLI Entry Point** (`bhavai/main.py`)
   - Click-based command-line interface
   - Interactive REPL (Read-Eval-Print Loop)
   - Dual operating modes: Plan Mode & Agent Mode
   - Rich terminal UI with panels and progress indicators

2. **Core Agent Engine** (`bhavai/agent.py`)
   - ReAct loop implementation
   - JSON parsing and validation
   - Tool execution orchestration
   - Error handling and recovery

3. **Tool System** (`bhavai/tools.py`)
   - Sandboxed file operations (read, write, update, list)
   - Safe command execution with blocklist
   - Path validation and security checks
   - Tool dispatch registry

4. **LLM Integration** (`bhavai/llm.py`)
   - Sarvam-105B API client
   - Exponential backoff retry logic
   - Rate limiting and error handling

5. **Configuration Management** (`bhavai/config.py`)
   - Environment variable loading
   - API key management
   - Logging configuration
   - Security settings

6. **Context Management** (`bhavai/context.py`)
   - Gitignore-aware folder tree generation
   - Path filtering and security
   - Workspace indexing

7. **Memory Management** (`bhavai/memory.py`)
   - Conversation history with character limits
   - Intelligent pruning for context window management
   - Role-based message storage

8. **Mode System** (`bhavai/modes.py`)
   - Plan Mode: Step-by-step task planning
   - Agent Mode: Autonomous execution
   - User feedback integration

## 🔧 Key Features

### Security & Safety
- **Zero-Deletion Policy**: Hardcoded constraints prevent file/directory deletions
- **Sandboxed Scope**: All operations confined to current working directory
- **Command Blocklist**: Blocks dangerous commands (rm, del, format, etc.)
- **Path Validation**: Prevents directory traversal attacks

### User Experience
- **Rich Terminal UI**: Beautiful progress indicators, panels, syntax highlighting
- **Dual Operating Modes**: Plan Mode (cautious) vs Agent Mode (autonomous)
- **Interactive REPL**: Real-time conversation with the AI
- **Gitignore Integration**: Respects .gitignore patterns

### Technical Excellence
- **Production Ready**: Robust error handling, logging, and monitoring
- **Extensible Tool System**: Easy to add new capabilities
- **Memory Management**: Intelligent conversation history pruning
- **API Resilience**: Retry logic and graceful degradation

## 📁 Project Structure

```
bhavai/
├── pyproject.toml          # Package configuration & global entry point
├── .env.example            # Environment variables template
├── README.md               # User documentation
├── bhavai/                 # Main package
│   ├── __init__.py         # Package initialization
│   ├── main.py             # Click CLI & interactive REPL entry point
│   ├── config.py           # Configuration loader & logger
│   ├── context.py          # Gitignore-aware folder tree builder
│   ├── memory.py           # In-session conversation history
│   ├── tools.py            # Sandboxed & blocklist-validated tools
│   ├── llm.py              # HTTPX client for Sarvam API with retries
│   ├── modes.py            # Plan vs Agent mode logic
│   └── agent.py            # Core ReAct loop runner
└── tests/                  # Test suite
    └── test_tools.py       # Pytest unit tests for tools
```

## 🛠️ Dependencies

### Core Dependencies
- `click>=8.0.0` - CLI framework
- `rich>=13.0.0` - Terminal UI components
- `python-dotenv>=1.0.0` - Environment variable management
- `httpx>=0.24.0` - HTTP client for API calls

### Development Dependencies
- `pytest>=7.0.0` - Testing framework

## 🚀 Installation & Setup

### Prerequisites
- Python 3.10 or higher
- Sarvam API key from https://dashboard.sarvam.ai/

### Installation Steps
1. Clone the repository
2. Install in editable mode: `pip install -e .`
3. Create `.env` file with API key:
   ```env
   SARVAM_API_KEY=your_api_key_here
   ```

## 📖 Documentation Plan

### 1. User Documentation (README.md)
- ✅ Installation and setup instructions
- ✅ Quick start guide
- ✅ Feature overview
- ✅ Usage examples
- ✅ Architecture diagram
- ✅ Security features explanation

### 2. API Documentation
- Tool function signatures and parameters
- Configuration options
- Error handling patterns
- Extension guidelines

### 3. Developer Documentation
- Code architecture overview
- Testing guidelines
- Contributing standards
- Extension development guide

### 4. Configuration Guide
- Environment variables reference
- Security settings
- Customization options

### 5. Troubleshooting Guide
- Common issues and solutions
- Debugging techniques
- Performance optimization

## 🎯 Future Enhancements

### Planned Features
- Email sending capability
- Web browsing integration
- Code execution sandbox
- Multi-agent collaboration
- Plugin system

### Technical Improvements
- Enhanced error recovery
- Performance optimizations
- Additional security features
- Better memory management

## 🔒 Security Considerations

- All file operations are sandboxed to current directory
- Command execution is strictly controlled
- API keys are handled securely
- No network access beyond API calls
- Input validation and sanitization

## 📊 Project Metrics

- **Lines of Code**: ~1,500+ lines
- **Test Coverage**: Basic tool testing
- **Dependencies**: 4 core dependencies
- **Python Version**: 3.10+
- **License**: MIT

This project represents a sophisticated implementation of a personal AI assistant with strong security guarantees and excellent user experience.