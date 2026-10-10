# Setup

Jonathan Ai runs on Python 3.10 or newer. API keys stay in `~/.clawd/config.json` (mode 0600). They are not written into git or the installer.

## 1. Install

From a checkout of https://github.com/GoDeskio/Clawd-Code:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows, `JonathanAi-Setup.exe` copies the source into `%USERPROFILE%\Jonathan\Jonathan-Ai` and can create the desktop shortcut.

## 2. Choose a provider

The desktop settings, install wizard, and `clawd login` offer:

- Anthropic Claude
- OpenAI GPT
- Hugging Face
- Local LLM (Ollama, LM Studio, vLLM, llama.cpp, or another OpenAI-compatible server on loopback or LAN)

```bash
clawd login
clawd desktop
```

Switching providers does not require a reinstall.

## 3. Check the install

```bash
clawd --version
python -m unittest discover -s tests -q
```
