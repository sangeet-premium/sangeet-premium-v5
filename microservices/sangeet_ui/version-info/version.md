---

# 🎵 **Sangeet PREMIUM V5** 🎵

<div align="center">

### *Where soul meets Music, not Noise...*

---

<img src="https://github.com/sangeet-premium/sangeet-premium-v5/releases/download/sole-assets/sangeet-premium-v5-logo.png" alt="Sangeet Logo" width="300" height="300" style="border-radius:30px;">

---

<!-- Platform Badges -->
<p align="center">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux"/>
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"/>
  <img src="https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=apple&logoColor=white" alt="macOS"/>
</p>


</div>

---

## 📋 **Quick Navigation**

| 🎭 **Features** | 🛠️ **Setup** | 📚 **Help** | 🤝 **Community** |
|:---:|:---:|:---:|:---:|
| [🎶 Music Player](#-what-is-sangeet-premium) | [🚀 Installation](#-installation-guide) | [📖 Documentation](#-documentation--support) | [🤝 Contributing](#-contributing) |
| [📱 Offline Platform](#-offline-listening-platform) | [🐳 Docker Setup](#-docker-installation) | [🆘 Support](#-getting-help) | [💬 Discussions](https://github.com/sangeet-premium/sangeet-premium-v5/discussions) |

---

## 🎭 **What Is Sangeet Premium?**

**Sangeet Premium** is a powerful web-based music platform that combines:

- **🎵 Advanced Music Player** - Feature-rich audio playback
- **📱 Offline Listening Platform** - Download and manage your music library  
- **🚀 Simple Setup** - Easy Docker-based installation

Perfect mixture of streaming, downloading, and personal music management!

---

## 🎶 **Music Player Features**

| Feature | Description | Status |
|---------|-------------|--------|
| 🎨 **Customizable UI** | Tailor interface to your preferences | ✅ Active |
| 🔧 **Replaceable Elements** | Swap components easily | ✅ Active |
| ♾️ **Infinite Possibilities** | Unleash creativity with personalization | ✅ Active |
| 🎯 **Personal Streaming** | Stream and manage your collection | ✅ Active |

---

## 📱 **Offline Listening Platform**

Transform your music experience with powerful offline capabilities:

### 🌟 **Key Features:**

- **💾 Downloaded Content Management** - Organize your music library efficiently
- **⚡ Custom Library Storage** - Store collections locally for instant access
- **🔄 Reduced Load Times** - Faster playback through optimized storage
- **🎼 Complete Collection Access** - Both online and offline music

---

## 🛠️ **Developer-Friendly Architecture**

Built with simplicity and extensibility in mind:

**📖 Clean Codebase** - Easy to understand and modify  
**🔧 Framework Flexibility** - Customize according to your needs  
**🐛 Debug-Friendly** - Troubleshoot issues with ease  
**🔓 Open Source** - Implement new features freely  
**🤝 Community-Driven** - Welcomes contributions  
**⚡ Performance** - Optimized for speed & efficiency  

---

## 🏗️ **System Architecture**

### 🏛️ **Core Components**

| Component | Purpose | Technology | Status |
|-----------|---------|------------|--------|
| 🚀 **Nginx Load Balancer** | Traffic routing & reverse proxy | Nginx | ✅ Active |
| 🖥️ **Sangeet UI Server** | Main application logic | Python/Bottle | ✅ Active |
| 🔊 **Stream Server** | Audio streaming service | Python/FastAPI | ✅ Active |
| 📥 **Download Server** | File download management | Python/Celery | ✅ Active |
| 🎤 **Lyrics Server** | Lyrics fetching & caching | Python/Flask | ✅ Active |
| 🤖 **Celery Worker** | Background task processing | Celery/Redis | ✅ Active |
| 🐘 **PostgreSQL** | Primary database | PostgreSQL 15 | ✅ Active |
| ⚡ **Redis Cache** | Caching & message broker | Redis 7 | ✅ Active |
| 📂 **Directory Monitor** | Auto-discovery of local files | Python Script | ✅ Active |
| ☁️ **Cloudflared Tunnel** | Secure external access | Cloudflare | 🟡 Optional |

### 🔄 **How It Works**

**Music Streaming Flow:**
1. User searches for music → UI Server queries database
2. User clicks play → Stream Server delivers audio
3. Background workers handle downloads and processing

**Download Process:**
1. User provides URL → Task queued in Redis
2. Celery worker processes download via yt-dlp
3. File saved locally and metadata stored in database

---

## 💻 **System Compatibility**

### 🏗️ **Supported Architectures**

**ARM-based Systems**  
🔧 x64, x32 | 🎯 Raspberry Pi Compatible | ⚡ Energy Efficient

**AMD64-based Systems**  
🔧 x64, x86 | 🎯 Desktop & Server | ⚡ High Performance

### 🖥️ **Operating System Support**

| OS | Status | Performance | Docker Support | Recommendation |
|---|:---:|:---:|:---:|---|
| 🐧 **Linux** | ✅ Preferred | ⭐⭐⭐⭐⭐ | Native | **Best Choice** |
| 🪟 **Windows** | ✅ Compatible | ⭐⭐⭐⭐ | Docker Desktop | **Mainstream** |
| 🍎 **macOS** | ✅ Supported | ⭐⭐⭐⭐ | Docker Desktop | **Creative Pro** |

---

## 🚀 **Installation Guide**

### **Prerequisites:**

- [ ] **Docker** installed ([Get Docker](https://docs.docker.com/get-docker/))
- [ ] **Docker Compose** available 
- [ ] **Git** installed ([Get Git](https://git-scm.com/downloads))
- [ ] **8GB RAM** minimum (16GB recommended)
- [ ] **10GB free disk space** minimum

---

## 🐳 **Docker Installation**

### **Step-by-Step Installation:**

#### **1️⃣ Clone the Repository**

```bash
# Clone the latest version
git clone "https://github.com/sangeet-premium/sangeet-premium-v5.git"
```

#### **2️⃣ Navigate to Project Directory**

```bash
cd sangeet-premium-v5

# Verify you're in the right directory
ls -la
```

#### **3️⃣ Build Docker Images**

```bash
# Build all services (this may take 5-10 minutes)
sudo docker compose -f sangeet-services.yaml build
```

#### **4️⃣ Start the Application**

**Foreground Mode** *(See logs in real-time)*
```bash
docker compose -f sangeet-services.yaml up
```

**Background Mode** *(Run as daemon)*
```bash
docker compose -f sangeet-services.yaml up -d
```

### **🔧 Advanced Options:**

**Custom Configuration:**
```bash
# Custom port mapping
export SANGEET_PORT=8080
docker compose -f sangeet-services.yaml up

# Custom music directory
export MUSIC_DIR=/path/to/your/music
docker compose -f sangeet-services.yaml up
```

**Troubleshooting Commands:**
```bash
# Check service status
docker compose -f sangeet-services.yaml ps

# View logs
docker compose -f sangeet-services.yaml logs

# Restart specific service
docker compose -f sangeet-services.yaml restart sangeet_ui_server

# Clean rebuild
docker compose -f sangeet-services.yaml down
docker system prune -f
docker compose -f sangeet-services.yaml build --no-cache
```

---

## 🎉 **Getting Started**

### 🎊 **Congratulations!** 

**Sangeet Premium V5** is now running on your system!

### 🎯 **First Steps:**

**1. Access Application:** [`http://localhost:3401`](http://localhost:3401) (local) for https : 3400

**2. Music Library Setup:**
- Add Local Folders: Settings → Library → Add Folder
- Enable Auto-Scan for new files
- Configure metadata preferences
- Import playlists (M3U, PLS formats)

**3. External Sources:**
- YouTube Integration: Paste URLs for download
- SoundCloud: Connect your account
- Spotify Playlists: Import metadata
- Radio Streams: Add internet stations

---

## 📖 **Documentation & Support**

### 📚 **Resources**

| Resource | Description | Link |
|----------|-------------|------|
| 🐛 **Issue Tracker** | Bug reports & feature requests | [Issues](https://github.com/sangeet-premium/sangeet-premium-v5/issues) |
| 💬 **Discussions** | Community Q&A | [Discussions](https://github.com/sangeet-premium/sangeet-premium-v5/discussions) |

### 🆘 **Getting Help**

**Having Issues?**
- **Bug Report** → Create Issue with bug template
- **Feature Request** → Create feature request  
- **Questions** → Start discussion for community help
- **Security Issues** → Email directly for private response

---

## 🤝 **Contributing**

### 🌟 **Join Our Growing Community!**

We welcome contributions from developers, designers, testers, and music enthusiasts!

### 🎯 **Ways to Contribute:**

**💻 Code** - Features, fixes, optimizations  
**🎨 Design** - UI/UX improvements, themes, icons  
**📝 Documentation** - Guides, tutorials, translations  
**🧪 Testing** - Bug reports, quality assurance  

**🎉 Thank you to all our amazing contributors! 🎉**

---

## ⚖️ **Legal Disclaimer & License**

### ⚠️ **IMPORTANT LEGAL INFORMATION** ⚠️

**BY USING THIS SOFTWARE, YOU ACKNOWLEDGE AND AGREE TO THE FOLLOWING:**

### 🎯 **Educational & Research Purpose**

This project is developed **SOLELY** for:
- ✅ Educational purposes
- ✅ Research and development  
- ✅ Demonstrating web technologies
- ❌ **NOT** for commercial use or piracy

### 🚫 **User Responsibility**

| Responsibility | User | Developers |
|----------------|:----:|:----------:|
| Legal Compliance | ✅ **YOU** | ❌ Not Us |
| Content Licensing | ✅ **YOU** | ❌ Not Us |
| Copyright Respect | ✅ **YOU** | ❌ Not Us |
| Local Law Adherence | ✅ **YOU** | ❌ Not Us |

### 📜 **License Information**

**🎓 Educational Use** - Custom Educational License (Learning & Research Only)  
**🔓 Open Source Components** - MIT License (Modify & Distribute)

### 🛡️ **Liability Disclaimer**

```
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
THE AUTHORS SHALL NOT BE LIABLE FOR ANY DAMAGES ARISING FROM USE.
```

### ✅ **Ethical Use Guidelines**

**Encouraged Use:**
- ✅ Learning programming concepts
- ✅ Understanding microservices architecture  
- ✅ Contributing to open source
- ✅ Educational projects and research

**Discouraged Use:**
- ❌ Copyright infringement or piracy
- ❌ Commercial exploitation without permission
- ❌ Violating platform terms of service
- ❌ Any illegal activities

---

## 🔗 **Quick Access Links**

<p align="center">
  <a href="https://github.com/sangeet-premium/sangeet-premium-v5">
    <img src="https://img.shields.io/badge/GitHub-Repository-black?style=for-the-badge&logo=github" alt="GitHub Repository"/>
  </a>
  <a href="https://github.com/sangeet-premium/sangeet-premium-v5/issues">
    <img src="https://img.shields.io/badge/Issues-Bug%20Reports-red?style=for-the-badge&logo=github" alt="Issues"/>
  </a>
  <a href="https://github.com/sangeet-premium/sangeet-premium-v5/discussions">
    <img src="https://img.shields.io/badge/Discussions-Community-blue?style=for-the-badge&logo=github" alt="Discussions"/>
  </a>
</p>

---

# _Made with ❤️ By Easy-Ware_

---

---
---