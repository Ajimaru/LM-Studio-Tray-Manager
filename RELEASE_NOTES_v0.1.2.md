# LM-Studio-Tray-Manager v0.1.2 - Release Notes

## 📋 Overview

**v0.1.2** is a maintenance and improvement release that focuses on **test coverage enhancement to 90%**, code quality improvements, and better documentation for developers.

---

## ✨ What's New

### Features & Enhancements
- **EditorConfig Support**: Added comprehensive EditorConfig configuration for consistent code styling across different editors and IDEs
- **Code Standards Documentation**: Introduced detailed code standards and best practices guide for contributors
- **Improved Release Packaging**: VERSION file now properly included in release distributions for better version tracking
- **Enhanced Logging**: Improved log output formatting in `lmstudio_autostart.sh` for better diagnostics

### 🔧 Bug Fixes & Improvements
- **Argument Parsing**: Simplified and cleaned up argument parsing by removing redundant model option
- **Test Coverage**: Enhanced subprocess command assertions and improved error handling in tray tests
- **Code Quality**: Improved timer assertions in TrayIcon constructor test with security annotations
- **Documentation**: Updated README with additional visibility badges and improved installation guidance

### 📚 Developer Experience
- Better code readability and maintainability improvements
- Comprehensive changelog integration in GitHub release workflow
- Clearer documentation for development setup and installation paths

---

## 📊 Testing & Quality

- **Test Coverage**: Enhanced to **90%** with improved assertions and error handling
- **Security**: Added security annotations and improved test assertions
- **Code Standards**: Established consistent code style and quality guidelines

---

## 📦 Installation

Download the latest release from: [GitHub Releases](https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases/tag/v0.1.2)

- **Binary Release** (Recommended): `LM-Studio-Tray-Manager-v0.1.2-binary.tar.gz`
- **Source Release**: `LM-Studio-Tray-Manager-v0.1.2-source.tar.gz`

---

## 🔍 Full Changelog

See the detailed changes between versions: [v0.1.1...v0.1.2](https://github.com/Ajimaru/LM-Studio-Tray-Manager/compare/v0.1.1...v0.1.2)

---

## ⚙️ Requirements

- Python 3.10+
- LM Studio App v0.4.3+ or LM Studio Daemon v0.0.3+
- Linux platform with GTK3 support

---

## 🙏 Thank You

Thanks to all contributors who helped improve LM-Studio-Tray-Manager!
